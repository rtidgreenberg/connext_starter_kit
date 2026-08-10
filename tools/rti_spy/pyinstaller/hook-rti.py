from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

hiddenimports = collect_submodules("rti")
binaries = collect_dynamic_libs("rti")
datas = collect_data_files("rti")