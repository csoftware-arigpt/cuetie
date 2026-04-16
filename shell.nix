{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  buildInputs = with pkgs; [
    python313Packages.pygobject3
    python313Packages.mutagen
    gtk3
    gobject-introspection
    ffmpeg
  ];
}
