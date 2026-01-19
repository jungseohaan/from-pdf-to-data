#!/usr/bin/env python3
"""PyInstaller 진입점 - 상대 import 문제 해결"""
import sys
import os

# 현재 디렉토리를 모듈 경로에 추가
if getattr(sys, 'frozen', False):
    # PyInstaller 번들된 앱
    base_path = sys._MEIPASS
else:
    # 일반 실행
    base_path = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, base_path)

# 앱 실행
from src.labeler import main
main()
