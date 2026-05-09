from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
datas = [
    ('src/materials/materials.db', 'src/materials'),
    ('src/generator/templates', 'src/generator/templates'),
]
datas += collect_data_files('cadquery')
datas += collect_data_files('OCP')

a = Analysis(
    ['src/main.py'], pathex=['.'], binaries=[], datas=datas,
    hiddenimports=collect_submodules('cadquery') + collect_submodules('OCP'),
    hookspath=[], cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    name='ANSYSWorkflowTool', debug=False, strip=False,
    upx=True, console=False, icon=None,
)
