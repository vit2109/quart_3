# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file сборка СЦ-отчёты для Windows."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata


ROOT = Path(SPECPATH).resolve()
datas = [
    (str(ROOT / "static"), "static"),
]
binaries = []
hiddenimports = [
    "infrastructure.knowledge.index_worker",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]


def collect_package(package_name):
    """Добавить динамические импорты, data-файлы и DLL пакета."""
    package_datas, package_binaries, package_hidden = collect_all(package_name)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hidden)


for package in (
    "chromadb",
    "sentence_transformers",
    "transformers",
    "huggingface_hub",
    "tokenizers",
    "safetensors",
    "fastexcel",
    "reportlab",
):
    collect_package(package)

hiddenimports.extend(collect_submodules("uvicorn"))
for distribution in (
    "chromadb",
    "sentence-transformers",
    "transformers",
    "huggingface-hub",
    "tokenizers",
    "safetensors",
):
    datas.extend(copy_metadata(distribution))

analysis = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "IPython", "jupyter", "notebook", "tkinter"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="SC-Reports",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # Сжатие нативных библиотек torch/tokenizers/Chroma может повреждать DLL
    # и проявляется именно при первой индексации.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
