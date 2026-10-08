# Microsoft app-local runtime notice

FS_elem's Windows installer may redistribute the Microsoft Visual C++ app-local runtime from the official Visual Studio build installation. These files remain Microsoft components; FS_elem does not assign them a new license.

The installer build records the exact DLL names, sizes and SHA-256 digests. The actual license text obtained from the official build installation or the Microsoft license-terms page is preserved under `docs/runtime-evidence/` in the installed application.

Official references:

- [Visual C++ redistribution](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files)
- [Visual Studio 2022 Community license terms](https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/)
- [Visual Studio 2022 distributable-code list](https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution)

This notice is a component inventory reference and does not replace Microsoft's actual license terms or grant additional rights.
