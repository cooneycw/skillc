"""Synthetic controller catalogues and emulated local arrivals; no transport."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import stamp_approval
from test_calibration import ROOT, _approved
from test_vm_admission import NOW, payloads, policy
from test_vm_identity import environment, observation

from skillc import calibration, live_wave, vm_admission, vm_identity
from skillc import wave_export as we

CONTROLS = ROOT / 'controls/wave-export'
CASES = json.loads((CONTROLS / 'cases.json').read_text())


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(value: bytes) -> str:
    return 'sha256:' + hashlib.sha256(value).hexdigest()


def declaration() -> calibration.CalibrationDeclaration:
    plan = json.loads((CONTROLS / 'plan.json').read_text())['wave_export']
    return calibration.parse_declaration(stamp_approval({**_approved(), 'execution_environment': environment(),
                                                        'operator_admission': policy(), 'wave_export': plan}))


def fixture(tmp_path: Path, *, second_nonstart: bool = True, dispatch_first: bool = True, allow_empty_capture: bool = True) -> tuple[Path, calibration.CalibrationDeclaration, dict[str, Any]]:
    decl = declaration()
    if not allow_empty_capture:
        declaration_data: dict[str, Any] = copy.deepcopy(dict(decl.data))
        declaration_data['wave_export']['waves'][0]['empty_capture_roles'] = []
        decl = calibration.parse_declaration(stamp_approval(declaration_data))
    env = environment()
    obs = observation(tmp_path / 'installation', env)
    facts = payloads()

    def collect(request: dict[str, Any]) -> dict[str, Any]:
        return {**{k: v for k, v in request.items() if k != 'check'},
                'observed_at': NOW, 'payload': facts[request['check']]}

    session = vm_admission.WindowSession(decl, collector=vm_admission.OperatorCollector('synthetic-operator', collect),
                                         vm_observation=obs, wall_clock=lambda: NOW, monotonic_clock=lambda: 10.0)
    receipts = []
    if dispatch_first:
        receipts = [session.collect('synthetic-wave-1', check) for check in vm_admission.CHECKS]
        session.request_dispatch('synthetic-wave-1', ROOT)
        session.close('synthetic-wave-1')
    if second_nonstart:
        with pytest.raises(calibration.DeclarationRefused):
            session.request_dispatch('synthetic-wave-2', ROOT)
        session.close('synthetic-wave-2')
    admission = session.report()
    identity = vm_identity.verify(env, obs)
    source = tmp_path / 'source'
    source.mkdir(parents=True)
    files: dict[str, bytes] = {'identity.json': canonical(identity), 'admission.json': canonical(admission)}
    dirs: set[str] = {''}
    waves = []
    for number, planned in enumerate(we.validate_plan(decl.data)['waves']):
        wave = planned['wave_id']
        roles = planned['roles']
        bindings = tuple(live_wave.RoleBinding(r, wave + '-' + r, None, 'synthetic-task', 0, 1,
                                               'synthetic-nonce', ('delivery.txt',)) for r in roles)
        plan = live_wave.WavePlan(wave, bindings, 'integrator', 100.0)
        verdict = live_wave.verdict(plan, None, lambda *_a: None)  # type: ignore[arg-type,return-value]
        path = wave + '/report.json'
        files[path] = canonical(verdict)
        records = [{'id': 'wave-report', 'kind': 'wave-report', 'role': None, 'availability': 'CAPTURED',
                    'path': path, 'reason': None}]
        for role in roles:
            rel = wave + '/' + role + '/role.json'
            files[rel] = canonical({'wave_id': wave, 'role': role, 'status': 'UNKNOWN'})
            records.append({'id': role + '-report', 'kind': 'role-report', 'role': role,
                            'availability': 'CAPTURED', 'path': rel, 'reason': None})
            for kind in ('transcript', 'capture'):
                rel = wave + '/' + role + '/' + kind
                if number == 0 and dispatch_first:
                    if kind == 'transcript':
                        files[rel] = b'synthetic transcript only\n'
                    else:
                        dirs.add(rel)  # Explicitly empty, allowed capture surface.
                records.append({'id': role + '-' + kind, 'kind': kind, 'role': role,
                                'availability': 'CAPTURED' if number == 0 and dispatch_first else 'UNKNOWN',
                                'path': rel if number == 0 and dispatch_first else None,
                                'reason': None if number == 0 and dispatch_first else 'synthetic nonstart, no role evidence'})
        if number == 0 and dispatch_first:
            for kind in ('turn', 'stdout', 'stderr', 'protocol', 'artifact'):
                rel = wave + '/integrator/' + kind + '.data'
                files[rel] = ('synthetic ' + kind + '\n').encode()
                records.append({'id': 'integrator-' + kind, 'kind': kind, 'role': 'integrator',
                                'availability': 'CAPTURED', 'path': rel, 'reason': None})
            for receipt in receipts:
                rel = wave + '/operator-' + str(receipt.sequence) + '.json'
                files[rel] = receipt.data
                records.append({'id': 'operator-' + str(receipt.sequence), 'kind': 'operator-receipt',
                                'role': None, 'availability': 'CAPTURED', 'path': rel, 'reason': None})
        waves.append({'wave_id': wave, 'roles': roles, 'task_status': verdict['status'], 'records': records})
    # Independent expected census comes from the controller's explicit writes,
    # not the export reader. A blind/empty production extractor cannot match it.
    for path in list(files) + list(dirs):
        parent = Path(path).parent
        while parent != Path('.'):
            dirs.add(parent.as_posix())
            parent = parent.parent
    for rel in sorted(dirs):
        (source / rel).mkdir(parents=True, exist_ok=True)
        (source / rel).chmod(0o700 if rel == '' else 0o755)
    entries = {rel: {'kind': 'directory', 'mode': 0o700 if rel == '' else 0o755} for rel in dirs}
    for rel, data in files.items():
        target = source / rel
        target.write_bytes(data)
        target.chmod(0o600)
        entries[rel] = {'kind': 'file', 'mode': 0o600, 'bytes': len(data), 'sha256': sha(data)}
    catalogue = {'version': 1, 'declaration_digest': calibration.declaration_digest(decl.data),
                 'window_id': admission['window_id'], 'vm_binding_digest': admission['vm_binding_digest'],
                 'identity_path': 'identity.json', 'admission_path': 'admission.json',
                 'admission_report': admission, 'waves': waves, 'entries': entries}
    return source, decl, catalogue


def arrival(tmp_path: Path) -> tuple[Path, we.FrozenExport, Path]:
    source, decl, catalogue = fixture(tmp_path)
    sealed = tmp_path / 'sealed'
    expected = we.freeze(source, decl, we.ControllerCatalogue.from_controller(catalogue), sealed)
    dest = tmp_path / 'arrival'
    dest.mkdir(mode=0o700)
    # This is a TEST transport emulator. Product code never copies/transfers.
    shutil.copy2(sealed / we.MANIFEST, dest / we.MANIFEST)
    shutil.copytree(source, dest / 'payload')
    return dest, expected, source


def mutate(dest: Path, action: str) -> None:
    payload = dest / 'payload'
    transcript = payload / 'synthetic-wave-1/integrator/transcript'
    if action == 'missing-transcript':
        transcript.unlink()
    elif action == 'omitted-role':
        shutil.rmtree(payload / 'synthetic-wave-1/worker')
    elif action == 'omitted-nonstart':
        shutil.rmtree(payload / 'synthetic-wave-2')
    elif action == 'missing-turn':
        (payload / 'synthetic-wave-1/integrator/turn.data').unlink()
    elif action == 'missing-stream':
        (payload / 'synthetic-wave-1/integrator/stdout.data').unlink()
    elif action == 'missing-record':
        (payload / 'synthetic-wave-1/report.json').unlink()
    elif action in ('corrupt-bytes', 'truncated'):
        transcript.write_bytes(b'different' if action == 'corrupt-bytes' else b'')
    elif action == 'file-mode':
        transcript.chmod(0o700)
    elif action == 'manifest-mode':
        (dest / we.MANIFEST).chmod(0o644)
    elif action == 'directory-mode':
        (payload / 'synthetic-wave-1/integrator/capture').chmod(0o700)
    elif action == 'extra-entry':
        (payload / 'extra.py').write_text('EXTRA = True\n')
    elif action == 'extra-envelope':
        (dest / 'transfer-receipt.json').write_text('{"success":true}\n')
    elif action == 'wrong-wave':
        p = payload / 'synthetic-wave-1/report.json'
        value = json.loads(p.read_bytes());value['wave_id'] = 'synthetic-other-wave';p.write_bytes(canonical(value))
    elif action == 'replaced-manifest-and-bytes':
        transcript.write_bytes(b'replaced coherent artifact')
        manifest = json.loads((dest / we.MANIFEST).read_bytes())
        row = manifest['catalogue']['entries']['synthetic-wave-1/integrator/transcript']
        row.update(bytes=len(transcript.read_bytes()), sha256=sha(transcript.read_bytes()))
        (dest / we.MANIFEST).write_bytes(canonical(manifest))
    elif action == 'symlink':
        transcript.unlink();transcript.symlink_to('/nonexistent-synthetic-target')
    elif action == 'missing-empty-surface':
        (payload / 'synthetic-wave-1/integrator/capture').rmdir()
    elif action == 'unreachable':
        shutil.rmtree(dest)
    elif action != 'none':
        raise AssertionError('unknown committed mutation')


def qualify(checker: Callable[[Path, we.FrozenExport], dict[str, Any]], tmp_path: Path) -> None:
    for case in CASES['cases']:
        root = tmp_path / case['name'];root.mkdir()
        dest, expected, source = arrival(root)
        mutate(dest, case['action'])
        result = checker(dest, expected)
        assert result['export_status'] == case['expected'], case['name']
        assert source.exists()


def test_committed_exact_and_lost_arrivals(tmp_path: Path) -> None:
    qualify(we.verify_arrival, tmp_path)


def test_committed_blind_checker_is_rejected(tmp_path: Path) -> None:
    control = CASES['qualification_controls'][0]
    assert control['checker'] == 'always-verified' and control['expected'] == 'REFUSED'
    with pytest.raises(AssertionError, match=control['witness']):
        qualify(lambda _dest, _expected: {'export_status': 'VERIFIED'}, tmp_path)


def test_integrity_keeps_unknown_nonstart_and_live_wave_denominator(tmp_path: Path) -> None:
    dest, expected, source = arrival(tmp_path)
    result = we.verify_arrival(dest, expected)
    assert result['export_status'] == 'VERIFIED' and result['planned'] == 2
    assert [w['task_status'] for w in result['waves']] == ['UNKNOWN', 'UNKNOWN']
    assert [w['nonstart'] for w in result['waves']] == [False, True]
    assert json.loads(expected.outcomes) == [{k: w[k] for k in ('wave_id', 'task_status', 'nonstart')}
                                            for w in result['waves']]
    mutate(dest, 'missing-transcript')
    lost = we.verify_arrival(dest, expected)
    assert lost['planned'] == 2 and all(w['export_status'] == 'UNKNOWN' for w in lost['waves'])
    assert [w['task_status'] for w in lost['waves']] == ['UNKNOWN', 'UNKNOWN']
    assert source.exists()


@pytest.mark.parametrize('status', ['PASS', 'FAIL'])
def test_export_integrity_does_not_regrade_task_outcome(tmp_path: Path, status: str) -> None:
    source, decl, catalogue = fixture(tmp_path)
    path = 'synthetic-wave-1/report.json'
    value = json.loads((source / path).read_bytes());value['status'] = status
    data = canonical(value);(source / path).write_bytes(data)
    catalogue['entries'][path].update(bytes=len(data), sha256=sha(data))
    catalogue['waves'][0]['task_status'] = status
    sealed = tmp_path / 'sealed'
    expected = we.freeze(source, decl, we.ControllerCatalogue.from_controller(catalogue), sealed)
    dest = tmp_path / 'arrival';dest.mkdir();shutil.copy2(sealed / we.MANIFEST, dest / we.MANIFEST)
    shutil.copytree(source, dest / 'payload')
    assert we.verify_arrival(dest, expected)['waves'][0]['task_status'] == status
    assert we.verify_arrival(dest, expected)['export_status'] == 'VERIFIED'
    mutate(dest, 'corrupt-bytes')
    assert we.verify_arrival(dest, expected)['waves'][0]['task_status'] == status
    assert we.verify_arrival(dest, expected)['export_status'] == 'UNKNOWN'


@pytest.mark.parametrize('fault', ['omitted-role', 'omitted-nonstart', 'missing-raw-receipt', 'wrong-wave-bytes',
                                  'uncatalogued-file', 'path-traversal'])
def test_invalid_source_catalogue_cannot_be_sealed(tmp_path: Path, fault: str) -> None:
    source, decl, catalogue = fixture(tmp_path)
    if fault == 'omitted-role':
        catalogue['waves'][0]['roles'].pop()
    elif fault == 'omitted-nonstart':
        catalogue['waves'].pop();catalogue['admission_report']['waves'].pop()
    elif fault == 'missing-raw-receipt':
        catalogue['waves'][0]['records'] = [r for r in catalogue['waves'][0]['records']
                                           if r['kind'] != 'operator-receipt']
    elif fault == 'wrong-wave-bytes':
        p = 'synthetic-wave-1/report.json';value = json.loads((source / p).read_bytes())
        value['wave_id'] = 'other';data = canonical(value);(source / p).write_bytes(data)
        catalogue['entries'][p].update(bytes=len(data), sha256=sha(data))
    elif fault == 'uncatalogued-file':
        (source / 'extra.py').write_bytes(b'EXTRA = 1\n')
    else:
        catalogue['waves'][0]['records'][0]['path'] = '../escape'
    with pytest.raises(we.ExportRefused):
        we.freeze(source, decl, we.ControllerCatalogue.from_controller(catalogue), tmp_path / 'sealed')
    assert source.exists() and not (tmp_path / 'sealed').exists()


def test_unreadability_is_injected_not_permission_based(tmp_path: Path) -> None:
    dest, expected, source = arrival(tmp_path)

    def unreadable(_root: Path) -> Any:
        raise PermissionError('synthetic unreadable destination')

    result = we.verify_arrival(dest, expected, reader=unreadable)
    assert result['export_status'] == 'UNKNOWN' and result['planned'] == 2 and source.exists()


def test_immutable_output_and_source_overlap_are_refused(tmp_path: Path) -> None:
    source, decl, catalogue = fixture(tmp_path)
    out = tmp_path / 'sealed'
    expected = we.freeze(source, decl, we.ControllerCatalogue.from_controller(catalogue), out)
    before = (out / we.MANIFEST).read_bytes()
    with pytest.raises(we.ExportRefused):
        we.freeze(source, decl, we.ControllerCatalogue.from_controller(catalogue), out)
    with pytest.raises(we.ExportRefused):
        we.freeze(source, decl, we.ControllerCatalogue.from_controller(catalogue), source / 'inside')
    assert (out / we.MANIFEST).read_bytes() == before and expected.manifest_sha256 == sha(before)
    assert source.exists() and not (source / 'inside').exists()


def test_source_drift_cannot_be_sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, decl, catalogue = fixture(tmp_path)
    read = we._inventory
    calls = 0

    def racing(root: Path, reader: we.Reader) -> dict[str, Any]:
        nonlocal calls
        result = read(root, reader);calls += 1
        if calls == 1:
            (source / 'synthetic-wave-1/integrator/transcript').write_text('changed\n')
        return result

    monkeypatch.setattr(we, '_inventory', racing)
    with pytest.raises(we.ExportRefused):
        we.freeze(source, decl, we.ControllerCatalogue.from_controller(catalogue), tmp_path / 'sealed')
    assert not (tmp_path / 'sealed').exists()


def test_provenance_is_not_an_admission_capability(tmp_path: Path) -> None:
    from test_vm_admission import session

    window, _ = session(tmp_path)
    bound = calibration.approval_record_binding(window._declaration)
    assert bound.declaration_digest == calibration.declaration_digest(window._declaration.data)
    with pytest.raises(calibration.DeclarationRefused, match='receipts'):
        calibration.require_approved(window._declaration, ROOT, vm_observation=window._observation,
                                     operator_admission=bound)  # type: ignore[arg-type]
    with pytest.raises(vm_admission.AdmissionRefused, match='unplanned'):
        window.request_dispatch(bound, ROOT)  # type: ignore[arg-type]


@pytest.mark.parametrize('second_nonstart', [True, False])
def test_export_retains_admission_nonstarts_without_requiring_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, second_nonstart: bool,
) -> None:
    source, decl, catalogue = fixture(tmp_path, second_nonstart=second_nonstart)
    original = copy.deepcopy(catalogue['admission_report'])

    def no_dispatch(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError('export must not ask for dispatch admission')

    monkeypatch.setattr(calibration, 'require_approved', no_dispatch)
    expected = we.freeze(source, decl, we.ControllerCatalogue.from_controller(catalogue), tmp_path / 'sealed')
    manifest = json.loads((tmp_path / 'sealed' / we.MANIFEST).read_bytes())
    assert manifest['catalogue']['admission_report'] == original
    assert original['waves'][1]['nonstart'] is True
    assert original['waves'][1]['state'] == ('CLOSED' if second_nonstart else 'PLANNED')
    assert json.loads(expected.outcomes)[1]['task_status'] == 'UNKNOWN'


@pytest.mark.parametrize('fault', ['bytes', 'mode'])
def test_freeze_does_not_repair_bad_source(tmp_path: Path, fault: str) -> None:
    source, decl, catalogue = fixture(tmp_path)
    path = source / 'synthetic-wave-1/integrator/transcript'
    if fault == 'bytes':
        path.write_bytes(b'bad source bytes')
    else:
        path.chmod(0o700)
    before = path.read_bytes(), path.stat().st_mode
    with pytest.raises(we.ExportRefused):
        we.freeze(source, decl, we.ControllerCatalogue.from_controller(catalogue), tmp_path / 'sealed')
    assert (path.read_bytes(), path.stat().st_mode) == before


@pytest.mark.parametrize('bound', ['MAX_ENTRIES', 'MAX_BYTES', 'MAX_DEPTH', 'MAX_FILE'])
def test_payload_reader_enforces_shared_bounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bound: str) -> None:
    source, _, _ = fixture(tmp_path)
    if bound == 'MAX_FILE':
        monkeypatch.setattr(we, bound, 1)
    else:
        monkeypatch.setattr(we.wave_capture, bound, 0 if bound == 'MAX_DEPTH' else 1)
    with pytest.raises((we.ExportRefused, we.Unreadable)):
        we._inventory(source, we.SafeTree)


def test_changed_plan_after_approval_cannot_be_sealed(tmp_path: Path) -> None:
    source, decl, catalogue = fixture(tmp_path)
    decl.data['wave_export']['waves'][0]['empty_capture_roles'] = []  # type: ignore[index]
    with pytest.raises(we.ExportRefused):
        we.freeze(source, decl, we.ControllerCatalogue.from_controller(catalogue), tmp_path / 'sealed')


def test_independent_expectation_is_required(tmp_path: Path) -> None:
    dest, _, source = arrival(tmp_path)
    with pytest.raises(we.ExportRefused, match='independently retained'):
        we.verify_arrival(dest, None)  # type: ignore[arg-type]
    assert source.exists()


def test_complete_unknown_identity_diagnostic_is_exportable_not_eligible(tmp_path: Path) -> None:
    source, decl, catalogue = fixture(tmp_path, dispatch_first=False)
    unknown = {'version': 1, 'scope': 'binding-and-install-match-only', 'status': 'UNKNOWN',
               'reason': 'synthetic identity observation unavailable',
               'declaration_digest': calibration.declaration_digest(decl.data),
               'window_id': catalogue['window_id']}
    catalogue['vm_binding_digest'] = sha(canonical(unknown))
    catalogue['admission_report']['vm_binding_digest'] = catalogue['vm_binding_digest']
    for path, value in [('identity.json', unknown), ('admission.json', catalogue['admission_report'])]:
        data = canonical(value);(source / path).write_bytes(data)
        catalogue['entries'][path].update(bytes=len(data), sha256=sha(data))
    expected = we.freeze(source, decl, we.ControllerCatalogue.from_controller(catalogue), tmp_path / 'sealed')
    dest = tmp_path / 'arrival';dest.mkdir()
    shutil.copy2(tmp_path / 'sealed' / we.MANIFEST, dest / we.MANIFEST)
    shutil.copytree(source, dest / 'payload')
    result = we.verify_arrival(dest, expected)
    assert result['export_status'] == 'VERIFIED' and result['planned'] == 2
    assert all(r['nonstart'] and r['task_status'] == 'UNKNOWN' for r in result['waves'])
    with pytest.raises(calibration.DeclarationRefused, match='observation'):
        calibration.require_approved(decl, ROOT)


def test_empty_capture_requires_explicit_approved_allowance(tmp_path: Path) -> None:
    source, decl, catalogue = fixture(tmp_path, allow_empty_capture=False)
    with pytest.raises(we.ExportRefused):
        we.freeze(source, decl, we.ControllerCatalogue.from_controller(catalogue), tmp_path / 'sealed')
    assert source.exists() and not (tmp_path / 'sealed').exists()


def test_admission_version_is_plain_integer(tmp_path: Path) -> None:
    _, decl, catalogue = fixture(tmp_path)
    catalogue['admission_report']['version'] = True
    with pytest.raises(we.ExportRefused):
        we._catalogue(catalogue, we.validate_plan(decl.data), calibration.declaration_digest(decl.data), environment())
