if(WIN32)
    add_subdirectory(clretwrc)
endif(WIN32)

if (NOT CLR_CMAKE_PLATFORM_ARCH_ARM)
    add_subdirectory(dbgshim)
    add_subdirectory(mscordac)
endif (NOT CLR_CMAKE_PLATFORM_ARCH_ARM)

add_subdirectory(mscordbi)
add_subdirectory(mscoree)
add_subdirectory(mscorpe)
add_subdirectory(mscorrc)
