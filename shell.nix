{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  nativeBuildInputs = with pkgs; [
    wrapGAppsHook3
    gobject-introspection
  ];
  buildInputs = with pkgs; [
    python313Packages.pygobject3
    python313Packages.mutagen
    python313Packages.charset-normalizer
    gtk3
    glib
    gsettings-desktop-schemas
    ffmpeg
  ];
  shellHook = ''
    for d in \
      ${pkgs.gtk3}/share/gsettings-schemas/${pkgs.gtk3.name} \
      ${pkgs.gsettings-desktop-schemas}/share/gsettings-schemas/${pkgs.gsettings-desktop-schemas.name}; do
      case ":$XDG_DATA_DIRS:" in
        *":$d:"*) ;;
        *) export XDG_DATA_DIRS="$d:$XDG_DATA_DIRS" ;;
      esac
    done
  '';
}
