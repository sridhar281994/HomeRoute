from os.path import exists, join

from pythonforandroid.logger import info
from pythonforandroid.recipes.sdl2_image import SDL2ImageRecipe as UpstreamSDL2ImageRecipe


class SDL2ImageRecipe(UpstreamSDL2ImageRecipe):
    def prebuild_arch(self, arch):
        build_dir = self.get_build_dir(arch.arch)
        external_dir = join(build_dir, "external")
        marker_path = join(external_dir, ".p4a_external_downloaded")

        if exists(marker_path):
            info("sdl2_image: external deps already downloaded; skipping download.sh")
            return

        legacy_jpeg_paths = (
            join(external_dir, "external", "jpeg"),
            join(external_dir, "jpeg"),
        )
        if any(exists(path) for path in legacy_jpeg_paths):
            info("sdl2_image: external deps already present; skipping download.sh")
            _touch_marker(marker_path)
            return

        super().prebuild_arch(arch)
        _touch_marker(marker_path)


def _touch_marker(path):
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("ok\n")
    except OSError:
        # Best-effort marker; build should not fail on write issues.
        pass


recipe = SDL2ImageRecipe()
