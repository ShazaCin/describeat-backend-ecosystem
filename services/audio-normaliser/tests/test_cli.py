"""Tests for the command-line interface."""

from __future__ import annotations

import json

import pytest

from describeat_audio.cli import main

from .conftest import requires_ffmpeg


def test_profiles_command_lists_both_profiles(capsys):
    assert main(["profiles"]) == 0
    output = capsys.readouterr().out

    assert "fingerprint" in output
    assert "ad-track" in output


def test_profiles_command_emits_json(capsys):
    assert main(["profiles", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert set(payload) == {"fingerprint", "ad-track"}
    assert payload["ad-track"]["channels"] == 1


def test_inspect_command_reports_the_file(capsys, stereo_flac):
    assert main(["inspect", str(stereo_flac)]) == 0
    output = capsys.readouterr().out

    assert "48 kHz" in output
    assert "stereo" in output


def test_inspect_command_emits_json(capsys, stereo_flac):
    assert main(["inspect", str(stereo_flac), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["audio"]["sample_rate"] == 48000
    assert payload["audio"]["channels"] == 2


def test_inspect_command_can_include_loudness(capsys, loud_mp3):
    assert main(["inspect", str(loud_mp3), "--loudness", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert "loudness" in payload
    assert "integrated_lufs" in payload["loudness"]


def test_a_missing_file_is_reported_as_an_error(capsys, tmp_path):
    assert main(["inspect", str(tmp_path / "nope.mp3")]) == 1
    assert "Error" in capsys.readouterr().err


def test_an_unknown_profile_is_rejected_by_the_parser():
    with pytest.raises(SystemExit):
        main(["normalise", "in.mp3", "-p", "nonsense"])


@requires_ffmpeg
def test_normalise_command_writes_the_output(capsys, loud_mp3, tmp_path):
    destination = tmp_path / "narration.mp3"

    assert main(["normalise", str(loud_mp3), "-p", "ad-track", "-o", str(destination)]) == 0

    assert destination.exists()
    output = capsys.readouterr().out
    assert "ad-track" in output
    assert "Verified against the profile" in output


@requires_ffmpeg
def test_normalise_command_emits_json(capsys, loud_mp3, tmp_path):
    destination = tmp_path / "narration.mp3"

    assert main([
        "normalise", str(loud_mp3), "-p", "ad-track",
        "-o", str(destination), "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["profile"]["name"] == "ad-track"
    assert payload["output"]["channels"] == 1


@requires_ffmpeg
def test_normalise_command_defaults_the_destination(capsys, loud_mp3, tmp_path):
    working = tmp_path / "narration.mp3"
    working.write_bytes(loud_mp3.read_bytes())

    assert main(["normalise", str(working), "-p", "ad-track"]) == 0
    assert working.exists()
