FROM archlinux:latest
RUN pacman -Syu --noconfirm --needed base-devel nodejs npm uv librsvg patchelf \
        libglvnd wayland libxcb nss libxkbcommon libxkbcommon-x11 fontconfig libdrm mesa alsa-lib libxcomposite libxdamage \
        libxrandr libxtst libxkbfile libxshmfence dbus at-spi2-core xcb-util-cursor xcb-util-image \
        xcb-util-keysyms xcb-util-renderutil xcb-util-wm \
    && pacman -Scc --noconfirm
