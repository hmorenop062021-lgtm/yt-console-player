"""Códigos de salida compartidos entre los controles y los wrappers bash.

Contrato:
  0  OK / el usuario salió
  1  error de mpv / conexión / ejecución
  10 búsqueda de canciones (YouTube)
  11 búsqueda de música / canciones (YouTube Music)
  12 búsqueda de álbumes
  13 búsqueda de playlists
"""

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_SEARCH_SONGS = 10
EXIT_SEARCH_MUSIC = 11
EXIT_SEARCH_ALBUMS = 12
EXIT_SEARCH_PLAYLISTS = 13

SEARCH_CODES = (
    EXIT_SEARCH_SONGS,
    EXIT_SEARCH_MUSIC,
    EXIT_SEARCH_ALBUMS,
    EXIT_SEARCH_PLAYLISTS,
)
