"""Collect one genuine execution per repeat and publish before journal commit."""
from pathlib import Path
import uuid

from scripts import campaign_v1 as campaign
from scripts import export_decisions as exporter
from scripts.experiment_archive import TRACE_SCHEMA


def collector(directory: Path, header: dict, manifest: dict):
    config = header["decision_trace"]
    source = exporter.source_provenance(header["identity"], header["base_commit"])
    if source["exporter_sha256"] != config["exporter_sha256"]:
        raise campaign.CampaignError("decision trace exporter compatibility conflict; use the original checkout")
    repeat_count = manifest["repeats"]

    def collect(case):
        attempt = uuid.uuid4().hex
        results, links = [], []
        for repeat in range(1, repeat_count + 1):
            result, records, failure = exporter.capture_execution(case, manifest)
            target = directory / "traces" / attempt / str(repeat)
            links.append(_publish(case, manifest, repeat, config["run_label"], target, source, result, records))
            if failure is not None:
                links.extend({"status": "not_run"} for _ in range(repeat, repeat_count))
                break
            results.append(result)
        return results, dict(schema=TRACE_SCHEMA, attempt=attempt, repeats=links), failure

    return collect


def _publish(case, manifest, repeat, label, target, source, result, records):
    try:
        meta = exporter.publish_execution(case, manifest, repeat, label, target, source, result, records,
                                          origin="campaign_execution")
        # The file contents and entry names were flushed by the exporter. On POSIX
        # also make its newly created parent entries durable before the journal.
        for parent in (target.parent, target.parent.parent, target.parent.parent.parent):
            campaign.sync_directory(parent)
        return dict(status=meta["replay"]["status"],
                    descriptor_sha256=campaign.sha((target / "export.json").read_bytes()))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError) as exc:
        return dict(status="collection_error", reason=type(exc).__name__)
