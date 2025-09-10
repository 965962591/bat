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
        '--windows-icon-from-ico=icon/rename.ico',
        '--windows-disable-console',
        '--windows-uac-admin',
        '--output-dir=output',        
        'rename_single.py',
        '--windows-file-version=1.5.2',
        '--windows-product-version=1.5.2',
        '--windows-file-description=文件重命名工具',
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