"""The README's result tables must be exactly what python/report.py renders from results/."""
import report


def test_readme_tables_match_results_files():
    machines, primary = report.load_all()
    text = report.README.read_text(encoding="utf-8")
    assert report.apply_blocks(text, report.render_blocks(machines, primary)) == text, (
        "README.md is out of date with results/: run python python/report.py"
    )


def test_readme_first_line_names_the_area():
    first = report.README.read_text(encoding="utf-8").splitlines()[0]
    assert first == (
        'A project for area 1, "SQL that saves you work" for the [MariaDB student database projects, '
        "2026-09](https://mariadb.org/bachelor_hackathon_2026-09/)."
    )
