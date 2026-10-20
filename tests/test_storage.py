from qf.storage import preferred_results_root, prepare_results_root


def test_preferred_results_root_uses_configured_ssd_path(tmp_path, monkeypatch):
    target = tmp_path/'ssd-results'
    monkeypatch.setenv('QF_RESULTS_ROOT', str(target))
    assert preferred_results_root(tmp_path/'project') == target.resolve()


def test_existing_results_are_copied_once_to_ssd_root(tmp_path, monkeypatch):
    project = tmp_path/'project'
    source = project/'results'/'20261020T000000-abcdef123456'
    source.mkdir(parents=True)
    (source/'metadata.json').write_text('{"run":"source"}', encoding='utf-8')
    target = tmp_path/'ssd-results'
    monkeypatch.setenv('QF_RESULTS_ROOT', str(target))

    assert prepare_results_root(project) == target.resolve()
    copied = target/source.name/'metadata.json'
    assert copied.read_text(encoding='utf-8') == '{"run":"source"}'
    copied.write_text('{"run":"local"}', encoding='utf-8')
    prepare_results_root(project)
    assert copied.read_text(encoding='utf-8') == '{"run":"local"}'
    assert (source/'metadata.json').read_text(encoding='utf-8') == '{"run":"source"}'


def test_relative_configured_results_root_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('QF_RESULTS_ROOT', 'relative/results')
    try:
        preferred_results_root(tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError('relative result path must be rejected')
