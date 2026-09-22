import os
import sys
import shutil
import subprocess

def install_pyinstaller():
    print("Checking if PyInstaller is installed...")
    try:
        import PyInstaller
        print("PyInstaller is already installed.")
    except ImportError:
        print("PyInstaller not found. Installing via pip...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
            print("PyInstaller successfully installed.")
        except subprocess.CalledProcessError as e:
            print(f"Error installing PyInstaller: {e}")
            sys.exit(1)

def build_exe():
    print("Starting build process...")
    
    # Import PyInstaller's main runner
    import PyInstaller.__main__
    
    # Base arguments
    args = [
        'app.py',
        '--onefile',
        '--noconsole',
        '--name=YT_Downloader_Pro',
        '--add-data=templates;templates',
        '--add-data=static;static',
        '--collect-all=webview',
        '--collect-all=clr_loader',
        '--collect-all=pythonnet',
        '--collect-all=curl_cffi',
        '--hidden-import=webview',
        '--hidden-import=clr_loader',
        '--hidden-import=pythonnet',
        '--hidden-import=clr_loader.ffi',
        '--hidden-import=curl_cffi',
        '--clean'
    ]
    
    # Generate and include application icon if available
    icon_path = 'app_icon.ico'
    if not os.path.exists(icon_path) and os.path.exists('store_logo_source.png'):
        try:
            from PIL import Image
            img = Image.open('store_logo_source.png')
            img.save(icon_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
            print(f"Generated {icon_path} from store_logo_source.png")
        except Exception as e:
            print(f"Could not generate {icon_path}: {e}")
    if os.path.exists(icon_path):
        print(f"Bundling icon: {icon_path}")
        args.append(f'--icon={icon_path}')

    # Include ffmpeg.exe and ffprobe.exe if they exist in the root folder
    if os.path.exists('ffmpeg.exe'):
        print("Found ffmpeg.exe. Bundling it...")
        args.append('--add-binary=ffmpeg.exe;.')
    else:
        print("WARNING: ffmpeg.exe not found in root directory. Executable will rely on system PATH.")
        
    if os.path.exists('ffprobe.exe'):
        print("Found ffprobe.exe. Bundling it...")
        args.append('--add-binary=ffprobe.exe;.')
    else:
        print("WARNING: ffprobe.exe not found in root directory. Executable will rely on system PATH.")

    print(f"Running PyInstaller with arguments: {args}")
    try:
        PyInstaller.__main__.run(args)
        print("PyInstaller completed successfully.")
    except Exception as e:
        print(f"PyInstaller execution failed: {e}")
        sys.exit(1)

    # Verify compiled executable in dist/
    dest_exe = os.path.join('dist', 'YT_Downloader_Pro.exe')
    if not os.path.exists(dest_exe):
        print("Error: Could not find the compiled executable in dist/ folder.")
        sys.exit(1)

    # Clean up build artifacts (optional but keeps workspace tidy)
    print("Cleaning up build artifacts...")
    try:
        if os.path.exists('build'):
            shutil.rmtree('build')
        if os.path.exists('YT_Downloader_Pro.spec'):
            os.remove('YT_Downloader_Pro.spec')
        print("Cleanup complete.")
    except Exception as e:
        print(f"Warning: Cleanup failed: {e}")

    print("\n" + "="*50)
    print("BUILD SUCCESSFUL!")
    print(f"Standalone EXE: {os.path.abspath(dest_exe)}")
    print("="*50)

if __name__ == '__main__':
    # Auto-switch to the project virtual environment if run directly from global Python
    if sys.prefix == sys.base_prefix:
        _app_dir = os.path.dirname(os.path.abspath(__file__))
        _venv_py = os.path.join(_app_dir, '.venv', 'Scripts', 'python.exe')
        if not os.path.exists(_venv_py):
            _venv_py = os.path.join(_app_dir, '.venv', 'bin', 'python')
        if os.path.exists(_venv_py) and os.environ.get('__YT_BUILD_VENV_SWITCHED') != '1':
            import subprocess
            os.environ['__YT_BUILD_VENV_SWITCHED'] = '1'
            print("Switching to project virtual environment (.venv)...")
            sys.exit(subprocess.call([_venv_py] + sys.argv))

    # Make sure we are in the script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    install_pyinstaller()
    build_exe()
