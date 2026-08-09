"""The controlled vocabularies a package is classified with.

Three questions get asked of a forensic toolbox, and they are genuinely
different questions:

    capabilities  what does this tool do?
    use_cases     when would I reach for it?
    evidence      what does it read?

Keeping them apart is the whole point. An earlier single list mixed "what it
does" with "when you would use it" and with attacker behaviour a tool might
happen to detect, which reads fine for one package and turns to noise across
fifty. Two tools can share a use case with nothing else in common.

Three axes is also the limit. Adding fields for features, workflows, outputs,
techniques and categories would each look reasonable alone and collectively
produce a taxonomy nobody maintains. These three answer what a person actually
searches for; anything further has to earn its place against that.

Every vocabulary is closed, and a term outside one is refused rather than
accepted as free text. Free tags fragment on the first synonym, and a catalog
where "evtx", "event log" and "eventlog" are three unrelated tags is worse than
one with no tags at all.

Terms carry aliases so search matches however someone phrases it. An alias is a
synonym for the idea, never the name of a tool or a rule format: putting
"sigma" on a general detection term would make every detection tool answer to a
search for one rule language. A format worth finding gets its own term.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ManifestError


@dataclass(frozen=True)
class Term:
    key: str
    label: str
    aliases: tuple[str, ...] = ()

    def matches(self, query: str) -> bool:
        query = query.strip().lower()
        if not query:
            return False
        return any(query in candidate.lower() for candidate in (self.key.replace("-", " "), self.label, *self.aliases))


def _index(*terms: Term) -> dict[str, Term]:
    return {term.key: term for term in terms}


# What the tool does.
CAPABILITIES = _index(
    Term("signature-scanning", "Signature scanning",
         ("signatures", "pattern matching", "byte patterns", "scanning")),
    Term("sigma-detection", "Sigma rule detection",
         ("sigma", "sigma rules", "detection rules")),
    Term("event-log-parsing", "Event log parsing",
         ("parse event logs", "evtx parsing", "log parsing")),
    Term("timeline-generation", "Timeline generation",
         ("timeline", "supertimeline", "chronology")),
    Term("registry-parsing", "Registry parsing",
         ("parse registry", "hive parsing")),
    Term("file-system-parsing", "File system parsing",
         ("parse ntfs", "filesystem parsing", "mft parsing")),
    Term("memory-analysis", "Memory analysis",
         ("analyse memory", "analyze memory", "volatile analysis")),
    Term("file-carving", "File carving",
         ("carving", "carve", "recover deleted", "unallocated")),
    Term("string-extraction", "String extraction",
         ("strings", "extract strings")),
    Term("hash-matching", "Hash matching",
         ("hashing", "hash sets", "known files")),
    Term("evidence-collection", "Evidence collection",
         ("collection", "acquire", "acquisition", "capture")),
    Term("decryption", "Decryption",
         ("decrypt", "encrypted", "password recovery")),
    Term("data-export", "Data export",
         ("export", "csv", "json output", "convert")),
    Term("visualisation", "Visualisation",
         ("visualisation", "visualization", "charts", "graphs", "viewer")),
)

# When an investigator reaches for it.
USE_CASES = _index(
    Term("incident-response", "Incident response",
         ("incident response", "ir", "breach", "compromise")),
    Term("forensic-triage", "Forensic triage",
         ("triage", "first response", "quick look")),
    Term("threat-hunting", "Threat hunting",
         ("hunting", "hunt", "proactive")),
    Term("malware-analysis", "Malware analysis",
         ("malware", "virus", "reverse engineering", "sample analysis")),
    Term("compromise-assessment", "Compromise assessment",
         ("compromise assessment", "health check", "assessment")),
    Term("evidence-review", "Evidence review and reporting",
         ("review", "reporting", "report", "presentation")),
)

# What data it reads.
EVIDENCE = _index(
    Term("windows-event-logs", "Windows event logs",
         ("evtx", "event log", "eventlog", "winevt", "security log", "sysmon")),
    Term("registry-hives", "Windows registry hives",
         ("registry", "hive", "ntuser", "regf", "software hive", "system hive")),
    Term("master-file-table", "NTFS master file table",
         ("mft", "master file table", "$mft", "ntfs")),
    Term("usn-journal", "NTFS change journal",
         ("usn", "journal", "$j", "change journal")),
    Term("prefetch-files", "Prefetch files",
         ("prefetch", "pf")),
    Term("amcache", "Amcache",
         ("amcache", "amcache.hve")),
    Term("shimcache", "Shimcache",
         ("shimcache", "appcompatcache", "application compatibility")),
    Term("shellbags", "Shellbags",
         ("shellbags", "shellbag", "folder access")),
    Term("jump-lists", "Jump lists",
         ("jump list", "jumplist", "automaticdestinations")),
    Term("shortcut-files", "Shortcut files",
         ("lnk", "shortcut", "link file")),
    Term("recycle-bin", "Recycle bin",
         ("recycle bin", "recyclebin", "deleted items")),
    Term("srum-database", "System resource usage database",
         ("srum", "srudb", "resource usage")),
    Term("scheduled-tasks", "Scheduled tasks",
         ("scheduled task", "task scheduler", "at job")),
    Term("browser-history", "Browser history",
         ("browser", "history", "chrome", "firefox", "edge", "cookies")),
    Term("email-stores", "Email stores",
         ("email", "mail", "pst", "ost", "mbox", "outlook")),
    Term("onedrive-logs", "OneDrive sync logs",
         ("onedrive", "odl", "sync log", "one drive")),
    Term("sqlite-databases", "SQLite databases",
         ("sqlite", "database")),
    Term("volume-shadow-copies", "Volume shadow copies",
         ("shadow copy", "vss", "volume shadow")),
    Term("memory-images", "Memory images",
         ("memory image", "ram dump", "memory dump", "raw memory")),
    Term("disk-images", "Disk images",
         ("disk image", "e01", "raw image", "dd image", "vmdk")),
    Term("network-captures", "Network captures",
         ("pcap", "packet capture", "network capture", "traffic")),
    Term("files", "Files of any kind",
         ("files", "file contents", "any file", "binaries", "executables")),
)

VOCABULARIES = {"capabilities": CAPABILITIES, "use_cases": USE_CASES, "evidence": EVIDENCE}


def checked(values, field: str) -> tuple[str, ...]:
    """Validate a classification list against its vocabulary."""
    vocabulary = VOCABULARIES[field]
    if values is None:
        return ()
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise ManifestError(f"{field} must be a list of strings")
    chosen: list[str] = []
    for item in values:
        key = item.strip().lower()
        if key not in vocabulary:
            raise ManifestError(f"{field} does not recognise {item!r}. Known values: {', '.join(sorted(vocabulary))}")
        if key in chosen:
            raise ManifestError(f"{field} lists {item!r} twice")
        chosen.append(key)
    return tuple(chosen)


def label(field: str, key: str) -> str:
    term = VOCABULARIES[field].get(key)
    return term.label if term else key


def matching_keys(field: str, query: str) -> set[str]:
    """Vocabulary keys a free-text query should reach."""
    return {key for key, term in VOCABULARIES[field].items() if term.matches(query)}
