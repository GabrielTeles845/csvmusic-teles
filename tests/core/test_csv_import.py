import pandas as pd

from csvmusic.core.csv_import import load_csv, tracks_from_csv


def test_csv_without_spotify_id_imports(tmp_path):
	path = tmp_path / "apple_music.csv"
	pd.DataFrame([
		{
			"Track name": "Everybody Needs Somebody to Love",
			"Artist name": "The Blues Brothers",
			"Playlist name": "Apple Export",
			"Duration (ms)": 206000,
		}
	]).to_csv(path, index=False)

	df = load_csv(path)
	tracks = tracks_from_csv(df)

	assert len(tracks) == 1
	assert tracks[0]["title"] == "Everybody Needs Somebody to Love"
	assert tracks[0]["artists"] == "The Blues Brothers"
	assert tracks[0]["sp_id"] is None
	assert tracks[0]["duration_ms"] == 206000
	assert tracks[0]["track_no"] == 1
	assert tracks[0]["disc_no"] == 1


def test_csv_import_preserves_explicit_track_and_disc_numbers(tmp_path):
	path = tmp_path / "album.csv"
	pd.DataFrame([{
		"Track name": "Finale",
		"Artist name": "Original Cast",
		"Playlist name": "Album",
		"Track number": 12,
		"Disc number": 2,
	}]).to_csv(path, index=False)

	track = tracks_from_csv(load_csv(path))[0]

	assert track["track_no"] == 12
	assert track["disc_no"] == 2


def test_exportify_csv_headers_and_filename_playlist_are_supported(tmp_path):
	path = tmp_path / "OFFICE_PLAYLIST.csv"
	pd.DataFrame([{
		"Track URI": "spotify:track:0s1aSsYlLIEiy16LjFWbdp",
		"Track Name": "Dirty Work",
		"Album Name": "Can't Buy A Thrill",
		"Artist Name(s)": "Steely Dan",
		"Release Date": "1972-01-01",
		"Duration (ms)": 187400,
	}]).to_csv(path, index=False)

	track = tracks_from_csv(load_csv(path))[0]

	assert track["title"] == "Dirty Work"
	assert track["artists"] == "Steely Dan"
	assert track["album"] == "Can't Buy A Thrill"
	assert track["playlist"] == "OFFICE_PLAYLIST"
	assert track["sp_id"] == "0s1aSsYlLIEiy16LjFWbdp"
	assert track["duration_ms"] == 187400
	assert track["year"] == 1972


def test_blank_playlist_names_fall_back_to_csv_filename(tmp_path):
	path = tmp_path / "My Playlist.csv"
	pd.DataFrame([{
		"Track name": "Song",
		"Artist name": "Artist",
		"Playlist name": "",
	}]).to_csv(path, index=False)

	track = tracks_from_csv(load_csv(path))[0]

	assert track["playlist"] == "My Playlist"


def test_csv_import_preserves_cover_url(tmp_path):
	path = tmp_path / "Artwork.csv"
	pd.DataFrame([{
		"Track name": "Song",
		"Artist name": "Artist",
		"Cover URL": "https://example.com/cover.jpg",
	}]).to_csv(path, index=False)

	track = tracks_from_csv(load_csv(path))[0]

	assert track["cover_url"] == "https://example.com/cover.jpg"


# Same header as the Spotify "liked songs" export that used to fail
# (BOM, ";" separator, CRLF, Portuguese names). The songs are invented.
_PT_HEADER = '"#";"Track Name";"Artist Name";"Álbum";"Adicionada em";"Duração";"Link"'


def _write_pt_export(path, rows):
	lines = [_PT_HEADER] + rows
	path.write_bytes(b"\xef\xbb\xbf" + "\r\n".join(lines).encode("utf-8"))


def test_semicolon_bom_portuguese_spotify_export_imports(tmp_path):
	path = tmp_path / "musicas_curtidas.csv"
	_write_pt_export(path, [
		'"1";"Canção Inventada";"Banda Fictícia, Outra Banda";"Álbum de Teste";"12 de out. de 2025";"2:57";"https://open.spotify.com/track/0000000000000000000001"',
		'"2";"Outra Faixa";"Cantora Exemplo";"Disco, Volume 2";"3 de set. de 2024";"10:05";"https://open.spotify.com/track/0000000000000000000002"',
	])

	tracks = tracks_from_csv(load_csv(path))

	assert len(tracks) == 2
	first = tracks[0]
	assert first["title"] == "Canção Inventada"
	assert first["artists"] == "Banda Fictícia, Outra Banda"
	assert first["album"] == "Álbum de Teste"
	assert first["playlist"] == "musicas_curtidas"
	assert first["sp_id"] == "0000000000000000000001"
	assert tracks[1]["album"] == "Disco, Volume 2"
	assert tracks[1]["sp_id"] == "0000000000000000000002"


def test_spanish_headers_without_accents_or_case_match(tmp_path):
	path = tmp_path / "lista.csv"
	path.write_bytes("Canción;ARTISTA;album;Enlace\nTema Uno;Grupo Falso;Disco;https://open.spotify.com/intl-es/track/0000000000000000000003?si=x\n".encode("cp1252"))

	track = tracks_from_csv(load_csv(path))[0]

	assert track["title"] == "Tema Uno"
	assert track["artists"] == "Grupo Falso"
	assert track["album"] == "Disco"
	assert track["sp_id"] == "0000000000000000000003"


def test_link_to_another_site_is_not_used_as_spotify_id(tmp_path):
	path = tmp_path / "mix.csv"
	path.write_text("Faixa,Artista,Link\nSong,Artist,https://music.youtube.com/watch?v=abc\n", encoding="utf-8")

	track = tracks_from_csv(load_csv(path))[0]

	assert track["sp_id"] is None


def test_missing_columns_error_lists_what_was_found(tmp_path):
	path = tmp_path / "bad.csv"
	path.write_text("Coluna A;Coluna B\n1;2\n", encoding="utf-8")

	try:
		load_csv(path)
	except ValueError as exc:
		assert "Coluna A" in str(exc)
	else:
		raise AssertionError("expected ValueError")


def test_portuguese_duration_column_in_mss_becomes_ms_with_precision(tmp_path):
	path = tmp_path / "curtidas.csv"
	_write_pt_export(path, [
		'"1";"Canção Inventada";"Banda Fictícia";"Álbum";"12 de out. de 2025";"2:57";"https://open.spotify.com/track/0000000000000000000001"',
		'"2";"Sem Duração";"Banda Fictícia";"Álbum";"12 de out. de 2025";"";"https://open.spotify.com/track/0000000000000000000002"',
	])

	tracks = tracks_from_csv(load_csv(path))

	assert tracks[0]["duration_ms"] == 177500
	assert tracks[0]["duration_source"] == "csv"
	assert tracks[0]["duration_precision_s"] == 1
	assert tracks[1]["duration_ms"] == 0
	assert tracks[1]["duration_source"] is None
	assert tracks[1]["duration_precision_s"] is None


def test_duration_ms_column_with_mss_text_is_still_read(tmp_path):
	path = tmp_path / "mixed.csv"
	path.write_text("Track name,Artist name,Duration (ms)\nA,B,2:57\nC,D,187400\n", encoding="utf-8")

	tracks = tracks_from_csv(load_csv(path))

	assert tracks[0]["duration_ms"] == 177500
	assert tracks[1]["duration_ms"] == 187400
	assert tracks[1]["duration_precision_s"] == 0


def test_duration_in_seconds_and_spanish_header(tmp_path):
	path = tmp_path / "es.csv"
	path.write_text("Canción;Artista;Duración (s)\nTema;Grupo;245\n", encoding="utf-8")

	track = tracks_from_csv(load_csv(path))[0]

	assert track["duration_ms"] == 245000
	assert track["duration_precision_s"] == 1


def test_bpm_tempo_column_does_not_override_duration(tmp_path):
	path = tmp_path / "exportify.csv"
	path.write_text("Track Name,Artist Name(s),Tempo,Duration (ms)\nSong,Artist,120.5,187400\n", encoding="utf-8")

	track = tracks_from_csv(load_csv(path))[0]

	assert track["duration_ms"] == 187400
