# cmake/platform.cmake
# Platform specific configuration and compiler flags

if(WIN32)
    message(STATUS "[DA-V] Target Platform: Windows (x64)")
    add_compile_definitions(DAV_PLATFORM_WINDOWS=1)
    add_compile_definitions(WIN32_LEAN_AND_MEAN)
    add_compile_definitions(NOMINMAX)
    add_compile_definitions(_CRT_SECURE_NO_WARNINGS)
    
    # Windows system libraries
    set(DAV_PLATFORM_LIBS
        ws2_32
        iphlpapi
        d3d11
        dxgi
        user32
        gdi32
        advapi32
        bcrypt
    )
elseif(UNIX AND NOT APPLE)
    message(STATUS "[DA-V] Target Platform: Linux")
    add_compile_definitions(DAV_PLATFORM_LINUX=1)
    
    # Linux system libraries
    set(DAV_PLATFORM_LIBS
        pthread
        dl
        rt
        m
        X11
        Xext
    )
endif()
