import os
import sys

"""
优先使用nuitka打包本项目为可执行程序aebox.exe

"""

if sys.platform == "win32":
    args = [
        'nuitka',
        '--standalone',
        '--lto=no',
        '--jobs=20' ,
        '--mingw64',
        '--show-progress',
        '--show-memory',              
        '--mingw64',      
        '--show-memory' ,
        '--enable-plugin=pyqt5',
        '--windows-icon-from-ico=icon/bat.ico',
        '--windows-disable-console',
        '--output-dir=output',        
        'bat.py',
        '--windows-file-version=3.8.2.9',
        '--windows-product-version=3.8.2.9',
        '--windows-file-description=bat脚本管理工具',
        '--windows-company-name=LongCheer',
        '--copyright=BarryChen'
    ]
else:
    args = [
        'pyinstaller',
        '-w',
        'hiviewer.py',
    ]


os.system(' '.join(args))