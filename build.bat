@echo off
REM Build ShadowSort.exe (dist\ShadowSort).   build.bat      = Lite (no AI, ~80 MB)
REM                                          build.bat ai   = Full (AI model bundled, ~1 GB)
cd /d "%~dp0"
if not exist .venv ( py -3 -m venv .venv || python -m venv .venv )
call .venv\Scripts\activate.bat
pip install -q pyinstaller

set EXTRA=
if /I "%1"=="ai" (
  pip install -r requirements-ai.txt
  if not exist models\clip python download_model.py
  set EXTRA=--collect-data transformers --copy-metadata transformers --copy-metadata tokenizers --copy-metadata huggingface-hub --copy-metadata safetensors --copy-metadata tqdm --copy-metadata regex --copy-metadata requests --copy-metadata packaging --copy-metadata filelock --copy-metadata numpy --copy-metadata pyyaml --copy-metadata torch
) else (
  pip install -q -r requirements.txt
)
REM face models are small (38 MB) - always bundle them so face recognition works offline
if not exist models\faces\face_recognition_sface_2021dec.onnx python download_model.py faces

pyinstaller --noconfirm --clean --windowed --name ShadowSort ^
  --icon assets\icon.ico --add-data "assets;assets" %EXTRA% main.py

REM PyInstaller puts --add-data inside _internal; the app also looks next to the exe for models\clip
if exist models\clip xcopy /E /I /Y models dist\ShadowSort\models >nul

echo.
echo Built: dist\ShadowSort\ShadowSort.exe
echo To make an installer, open installer.iss in Inno Setup and press Compile.
