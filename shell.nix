{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  buildInputs = with pkgs; [
    python313Packages.pygobject3
    python313Packages.mutagen
    python313Packages.charset-normalizer
    gtk3
    gobject-introspection
    ffmpeg
  ];
}
