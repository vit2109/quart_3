"""REST-эндпоинты аналитических операций над наборами данных."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from core.security import require_role
from domain.entities.user import User, UserRole
from application.use_cases.analysis.analysis_service import AnalysisService
from api.v1.endpoints.export_data import AggregationSpec, FilterSpec
from core.exceptions import AppException
import logging

router = APIRouter(prefix="/analysis", tags=["analysis"])
logger = logging.getLogger(__name__)


class AIAnalyzeRequest(BaseModel):
    """Запрос на развёрнутый AI-анализ набора данных."""

    question: Optional[str] = Field(
        default=None,
        description="Вопрос или фокус анализа; если пусто — полный обзор",
    )
    save_report: bool = True
    include_correlations: bool = True
    sample_rows: int = Field(default=12, ge=3, le=30)
    filters: Optional[List[FilterSpec]] = None
    group_by: Optional[List[str]] = None
    aggregations: Optional[List[AggregationSpec]] = None
    background: bool = Field(
        default=True,
        description="Запустить в фоне и вернуть job_id (рекомендуется)",
    )
    model_path: Optional[str] = Field(
        default=None,
        description="Путь к GGUF-модели из каталога models/; пусто — из .env",
    )


class PeriodRange(BaseModel):
    """Интервал дат для сравнения."""

    from_date: str = Field(..., alias="from")
    to_date: str = Field(..., alias="to")

    model_config = {"populate_by_name": True}


class ComparePeriodsRequest(BaseModel):
    """Сравнение метрик между двумя периодами."""

    date_col: str
    period_a: PeriodRange
    period_b: PeriodRange
    metrics: Optional[List[str]] = None


class NLQueryRequest(BaseModel):
    """Вопрос на естественном языке к табличным данным."""

    question: str = Field(min_length=3, max_length=2000)


class StatisticsRequest(BaseModel):
    """Статистика по колонкам с опциональными фильтрами."""

    columns: List[str] = Field(default_factory=list)
    filters: List[FilterSpec] = Field(default_factory=list)


class CorrelationsRequest(BaseModel):
    """Корреляции с опциональными фильтрами."""

    method: str = "pearson"
    filters: List[FilterSpec] = Field(default_factory=list)


class AnomaliesRequest(BaseModel):
    """Поиск аномалий с фильтрами."""

    columns: List[str] = Field(default_factory=list)
    filters: List[FilterSpec] = Field(default_factory=list)


class KpisRequest(BaseModel):
    """KPI с агрегацией по каждому полю."""

    definitions: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    filters: List[FilterSpec] = Field(default_factory=list)


class ExploreChartSpec(BaseModel):
    """Параметры графика для универсального анализа."""

    enabled: bool = False
    type: str = "bar"
    label_column: Optional[str] = None
    value_column: Optional[str] = None
    title: Optional[str] = None
    top_n: int = Field(default=30, ge=3, le=100)


class ExploreRequest(BaseModel):
    """Универсальный анализ: фильтры, группировка, агрегации, график."""

    mode: str = Field(default="grouped", description="grouped или raw")
    filters: List[FilterSpec] = Field(default_factory=list)
    group_by: List[str] = Field(default_factory=list)
    aggregations: List[AggregationSpec] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)
    sort_by: Optional[str] = None
    sort_dir: str = "asc"
    limit: int = Field(default=200, ge=1, le=2000)
    chart: Optional[ExploreChartSpec] = None


class TimeseriesRequest(BaseModel):
    """Динамика метрик по оси времени."""

    date_col: str
    metrics: List[str] = Field(default_factory=list)
    granularity: str = Field(default="day", pattern="^(day|week|month)$")
    agg: str = Field(default="sum", pattern="^(sum|mean|min|max|count)$")
    filters: List[FilterSpec] = Field(default_factory=list)
    limit: int = Field(default=500, ge=10, le=2000)


class ParetoRequest(BaseModel):
    """Pareto / топ-N с накопленной долей и HHI."""

    group_by: List[str] = Field(default_factory=list)
    metric: str
    agg: str = Field(default="sum", pattern="^(sum|mean|count)$")
    top_n: int = Field(default=20, ge=5, le=100)
    filters: List[FilterSpec] = Field(default_factory=list)


class SqlTableSpec(BaseModel):
    alias: str
    dataset_id: int


class SqlQueryRequest(BaseModel):
    sql: str = Field(min_length=8, max_length=8000)
    tables: List[SqlTableSpec] = Field(default_factory=list)
    limit: int = Field(default=500, ge=1, le=2000)


class UnifiedAskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    knowledge_top_k: int = Field(default=5, ge=1, le=15)
    include_table_query: bool = True
    include_knowledge: bool = True
    save_report: bool = False


def _service() -> AnalysisService:
    """Фабрика сервиса анализа (новый экземпляр на запрос)."""
    return AnalysisService()


@router.post("/statistics/{dataset_id}")
async def get_statistics(
    dataset_id: int,
    body: Optional[StatisticsRequest] = None,
    columns: Optional[List[str]] = Query(None),
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Описательная статистика по колонкам (mean, median, std, квантили)."""
    try:
        req = body or StatisticsRequest()
        cols = req.columns or columns or None
        stats = await _service().get_statistics(
            dataset_id,
            cols,
            filters=[f.model_dump() for f in req.filters],
        )
        return {"status": "success", "data": stats}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/correlations/{dataset_id}")
async def get_correlations(
    dataset_id: int,
    body: Optional[CorrelationsRequest] = None,
    method: str = Query("pearson", pattern="^(pearson|spearman)$"),
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Матрица корреляций Pearson или Spearman между числовыми колонками."""
    try:
        req = body or CorrelationsRequest(method=method)
        corr_method = req.method or method
        correlations = await _service().get_correlations(
            dataset_id,
            corr_method,
            filters=[f.model_dump() for f in req.filters],
        )
        return {"status": "success", "data": correlations}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Error getting correlations: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/anomalies/{dataset_id}")
async def detect_anomalies(
    dataset_id: int,
    body: AnomaliesRequest,
    contamination: float = Query(0.1, ge=0.01, le=0.5),
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Поиск аномалий по Z-score; contamination — доля выбросов (0.01–0.5)."""
    try:
        if not body.columns:
            raise HTTPException(status_code=400, detail="columns required")
        anomalies = await _service().detect_anomalies(
            dataset_id,
            body.columns,
            contamination,
            filters=[f.model_dump() for f in body.filters],
        )
        return {"status": "success", "data": anomalies}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Error detecting anomalies: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/forecast/{dataset_id}")
async def forecast_data(
    dataset_id: int,
    date_col: str,
    target_col: str,
    periods: int = Query(30, ge=1, le=365),
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Прогноз временного ряда (baseline_drift) на заданное число периодов."""
    try:
        forecast = await _service().forecast(
            dataset_id, date_col, target_col, periods
        )
        return {"status": "success", "data": forecast}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Error forecasting: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/kpis/{dataset_id}")
async def calculate_kpis(
    dataset_id: int,
    body: Dict[str, Any],
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Расчёт KPI: body — {колонка: {agg}} или {definitions, filters}."""
    try:
        if "definitions" in body or "filters" in body:
            req = KpisRequest(**body)
            definitions = req.definitions
            filters = [f.model_dump() for f in req.filters]
        else:
            definitions = body
            filters = []
        kpis = await _service().calculate_kpis(
            dataset_id, definitions, filters=filters
        )
        return {"status": "success", "data": kpis}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Error calculating KPIs: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/explore/{dataset_id}")
async def explore_dataset(
    dataset_id: int,
    body: ExploreRequest,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Универсальный анализ: фильтры, группировка, агрегации по полям, график."""
    try:
        chart = body.chart.model_dump() if body.chart else None
        result = await _service().explore(
            dataset_id,
            mode=body.mode,
            filters=[f.model_dump() for f in body.filters],
            group_by=body.group_by,
            aggregations=[a.model_dump() for a in body.aggregations],
            columns=body.columns,
            sort_by=body.sort_by,
            sort_dir=body.sort_dir,
            limit=body.limit,
            chart=chart,
        )
        return {"status": "success", "data": result}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Error in explore analysis: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/timeseries/{dataset_id}")
async def timeseries_dataset(
    dataset_id: int,
    body: TimeseriesRequest,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Динамика метрик по колонке даты (day/week/month)."""
    try:
        result = await _service().timeseries(
            dataset_id,
            body.date_col,
            body.metrics,
            granularity=body.granularity,
            agg=body.agg,
            filters=[f.model_dump() for f in body.filters],
            limit=body.limit,
        )
        return {"status": "success", "data": result}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Error in timeseries analysis: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/pareto/{dataset_id}")
async def pareto_dataset(
    dataset_id: int,
    body: ParetoRequest,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Pareto: топ-N групп, доля и накопленная доля, HHI."""
    try:
        result = await _service().pareto(
            dataset_id,
            body.group_by,
            body.metric,
            agg=body.agg,
            top_n=body.top_n,
            filters=[f.model_dump() for f in body.filters],
        )
        return {"status": "success", "data": result}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Error in pareto analysis: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/compare/{dataset_id}")
async def compare_periods(
    dataset_id: int,
    body: ComparePeriodsRequest,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Сравнение метрик между двумя периодами (YoY / MoM / custom)."""
    try:
        result = await _service().compare_periods(
            dataset_id,
            body.date_col,
            body.period_a.model_dump(by_alias=True),
            body.period_b.model_dump(by_alias=True),
            body.metrics,
        )
        return {"status": "success", "data": result}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Error comparing periods: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/nl-query/{dataset_id}")
async def nl_query_dataset(
    dataset_id: int,
    body: NLQueryRequest,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """NL-запрос к таблице: LLM → безопасный Polars-план → результат."""
    from application.use_cases.ai.nl_query_service import NLQueryService

    try:
        result = await NLQueryService().query(
            dataset_id,
            body.question,
            user_email=current_user.email,
        )
        return {"status": "success", "data": result}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"NL query error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ai/analyze/{dataset_id}")
async def ai_analyze(
    dataset_id: int,
    body: Optional[AIAnalyzeRequest] = None,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Развёрнутый AI-анализ датасета через локальную LLM."""
    from application.use_cases.ai.ai_service import AIService

    payload = body or AIAnalyzeRequest()
    try:
        if payload.background:
            from application.use_cases.jobs.job_service import JobService

            job_payload = {
                "dataset_id": dataset_id,
                "question": payload.question,
                "save_report": payload.save_report,
                "include_correlations": payload.include_correlations,
                "sample_rows": payload.sample_rows,
                "filters": [f.model_dump() for f in (payload.filters or [])],
                "group_by": payload.group_by,
                "aggregations": [a.model_dump() for a in (payload.aggregations or [])],
                "model_path": payload.model_path,
            }
            run = await JobService().submit("ai_analyze", job_payload)
            return {
                "status": "success",
                "data": {
                    "job_id": run["id"],
                    "status": run.get("status", "queued"),
                    "dataset_id": dataset_id,
                },
            }

        result = await AIService().analyze_dataset(
            dataset_id,
            question=payload.question,
            save_report=payload.save_report,
            include_correlations=payload.include_correlations,
            sample_rows=payload.sample_rows,
            filters=[f.model_dump() for f in (payload.filters or [])],
            group_by=payload.group_by,
            aggregations=[a.model_dump() for a in (payload.aggregations or [])],
            model_path=payload.model_path,
        )
        return {"status": "success", "data": result}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Error in AI analysis: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sql")
async def run_sql_query(
    body: SqlQueryRequest,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """SQL-lite: SELECT через Polars SQLContext (один или несколько наборов)."""
    from application.use_cases.query.sql_query_service import SqlQueryService

    try:
        result = await SqlQueryService().execute(
            body.sql,
            [t.model_dump() for t in body.tables],
            limit=body.limit,
        )
        return {"status": "success", "data": result}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"SQL query error: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/unified-ask/{dataset_id}")
async def unified_ask(
    dataset_id: int,
    body: UnifiedAskRequest,
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Сквозной ответ: табличные данные + база знаний."""
    from application.use_cases.ai.unified_context_service import UnifiedContextService

    try:
        result = await UnifiedContextService().ask(
            dataset_id,
            body.question,
            knowledge_top_k=body.knowledge_top_k,
            include_table_query=body.include_table_query,
            include_knowledge=body.include_knowledge,
            save_report=body.save_report,
        )
        return {"status": "success", "data": result}
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Unified ask error: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/ai/models")
async def ai_models_list(
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Список GGUF-моделей в каталоге models/."""
    from infrastructure.ai.model_manager import list_local_models

    models = list_local_models()
    return {"status": "success", "data": models}


@router.get("/ai/health")
async def ai_health(
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Проверка доступности локальной LLM (llama-cpp / transformers)."""
    from infrastructure.ai.llama_client import LocalLLMClient

    return {"status": "success", "data": await LocalLLMClient().health()}


@router.post("/rag/query/{collection_name}")
async def rag_query(
    collection_name: str,
    query: str,
    n_results: int = Query(5, ge=1, le=20),
    current_user: User = Depends(require_role(UserRole.ANALYST)),
):
    """Legacy RAG endpoint — перенаправляет на /knowledge/search."""
    from application.use_cases.knowledge.knowledge_service import KnowledgeService

    data = await KnowledgeService().search(
        query,
        mode="hybrid",
        top_k=n_results,
        collection=collection_name or "quart_knowledge",
    )
    return {"status": "success", "data": data}
