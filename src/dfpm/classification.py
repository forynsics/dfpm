"""The controlled vocabularies a package is classified with.

Four axes answering four different questions: `disciplines` (which part of the
field), `capabilities` (what it does), `use_cases` (when you would reach for it)
and `evidence` (what it reads). Each vocabulary is closed, so a term outside one
is refused rather than accepted as free text, and each term carries aliases so a
search matches however it is phrased.

Why the axes are kept apart, what has to be true of a new one, and what an alias
may and may not be are set out in docs/manifest-v1.md. That reasoning belongs
with the format it constrains, and is deliberately not repeated here.
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


# Which part of the field the tool belongs to. Mirrors how the discipline is
# taught and how somebody new to it browses, which is the point: this axis is
# for people who cannot yet name what they are looking for.
DISCIPLINES = _index(
    Term("windows-forensics", "Windows forensics",
         ("windows", "win", "microsoft")),
    Term("macos-forensics", "macOS forensics",
         ("mac", "macos", "osx", "os x", "apple", "darwin")),
    Term("linux-forensics", "Linux forensics",
         ("linux", "unix", "ubuntu", "debian style", "posix")),
    Term("smartphone-forensics", "Smartphone forensics",
         ("smartphone", "mobile", "phone", "ios", "android", "iphone", "handset")),
    Term("network-forensics", "Network forensics",
         ("network", "traffic", "packets", "wire")),
    Term("cloud-forensics", "Cloud forensics",
         ("cloud", "saas", "aws", "azure", "gcp", "microsoft 365")),
    Term("memory-forensics", "Memory forensics",
         ("memory", "ram", "volatile")),
    Term("malware-analysis", "Malware analysis",
         ("malware", "virus", "reverse engineering", "sample analysis", "rem")),
)

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
    Term("plist-files", "Property lists",
         ("plist", "property list", "preferences")),
    Term("fsevents", "macOS file system events",
         ("fsevents", "fsevent", "file system events")),
    Term("unified-logs", "macOS unified logs",
         ("unified log", "logarchive", "log archive", "asl")),
    Term("spotlight-metadata", "Spotlight metadata",
         ("spotlight", "mdworker", "store.db")),
    Term("quarantine-events", "Download quarantine records",
         ("quarantine", "gatekeeper", "downloads")),
    Term("syslog", "Syslog",
         ("syslog", "var log", "messages", "auth log")),
    Term("systemd-journal", "systemd journal",
         ("journald", "journalctl", "systemd journal")),
    Term("shell-history", "Shell history",
         ("bash history", "zsh history", "shell history", "command history")),
    Term("audit-logs", "Audit daemon logs",
         ("auditd", "audit log", "linux audit")),
    Term("ios-backups", "iOS backups",
         ("ios backup", "itunes backup", "iphone backup")),
    Term("android-images", "Android images",
         ("android", "adb", "android image")),
    Term("cloud-audit-logs", "Cloud audit logs",
         ("cloudtrail", "azure activity", "unified audit log", "gcp audit", "cloud logs")),
    Term("netflow-records", "Flow records",
         ("netflow", "flow records", "ipfix")),
    Term("files", "Files of any kind",
         ("files", "file contents", "any file", "binaries", "executables")),
)

VOCABULARIES = {
    "disciplines": DISCIPLINES,
    "capabilities": CAPABILITIES,
    "use_cases": USE_CASES,
    "evidence": EVIDENCE,
}


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


def vocabulary() -> dict[str, list[dict[str, str]]]:
    """Every term, so an interface can render choices it has no business inventing.

    A page offering "browse by discipline" needs the full list, including the
    disciplines nothing is catalogued under yet, or its buttons appear and
    vanish as the catalog grows. Reading it from here rather than hard-coding it
    is what stops the two drifting apart.

    Aliases travel too. They exist so a search matches however somebody phrases
    it, which is no use at all if only this module can see them: an interface
    searching the catalog would have to guess that "evtx" means the same as
    "Windows event logs", and would guess wrong.
    """
    return {
        field: [{"key": term.key, "label": term.label, "aliases": list(term.aliases)} for term in terms.values()]
        for field, terms in VOCABULARIES.items()
    }


def label(field: str, key: str) -> str:
    term = VOCABULARIES[field].get(key)
    return term.label if term else key


def matching_keys(field: str, query: str) -> set[str]:
    """Vocabulary keys a free-text query should reach."""
    return {key for key, term in VOCABULARIES[field].items() if term.matches(query)}
