@echo off
REM Установка PyTorch для RTX 5090 (CUDA 12.8)
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip3 install -r requirements.txt

