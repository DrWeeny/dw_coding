# Must have Python27 and Visual Studio 2010 installed

set oldpath=%path%
set oldinclude=%INCLUDE%
set oldlib=%LIB%
set oldlibpath=%LIBPATH%

rem Make compile with VS2010
SET VS90COMNTOOLS=%VS100COMNTOOLS%

call "C:\Program Files (x86)\Microsoft Visual Studio 10.0\VC\vcvarsall.bat" x86_amd64

rem Checkout temp
p4 edit build\temp.win-amd64-2.7\...

rem Checkout build
p4 edit build\lib.win-amd64-2.7\p4api.pyd
p4 edit build\lib.win-amd64-2.7\p4.py

rem Nuke files before build
del build\lib.win-amd64-2.7\P4.py
del build\lib.win-amd64-2.7\P4API.pyd

rem Run Build
C:\python27\python.exe setup.py build 


rem Revert temp
p4 revert build\temp.win-amd64-2.7\...


path %oldpath%
set INCLUDE=%oldinclude%
set LIB=%oldlib%
set LIBPATH=%oldlibpath%
