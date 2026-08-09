"""The controlled vocabularies a package is classified with.

Two questions get asked of a forensic toolbox, and they are not the same
question. "What am I trying to find out?" and "what am I looking at?" pull
different tools, so they are separate axes rather than one bag of tags: a
search for malware should surface a scanner, and a search for a sync log
should surface the tool that reads one.

Both vocabularies are closed. Free-text tags fragment the moment two people
write the same idea differently, and a catalog where "evtx", "event log" and
"eventlog" are three unrelated tags is worse than no tags at all. Adding a term
is a deliberate change reviewed alongside the package that needs it.

Each term carries aliases so search matches how people actually type. Nobody
searching for a master file table types "mft" every time.

Aliases are synonyms for the idea, never the name of a tool or a rule format.
Putting "sigma" on threat hunting makes every hunting tool answer to a search
for one specific rule language, which is worse than not matching at all. A
product name belongs on the package that implements it, or earns a term of its
own on the artifact axis.
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
        haystacks = (self.key.replace("-", " "), self.label.lower(), *self.aliases)
        return any(query in candidate.lower() for candidate in haystacks)


def _index(*terms: Term) -> dict[str, Term]:
    return {term.key: term for term in terms}


# What forensic question the package helps answer.
SOLVES = _index(
    Term("malware-identification", "Malware identification",
         ("malware", "virus", "signature", "ioc", "indicator")),
    Term("threat-hunting", "Threat hunting",
         ("hunting", "hunt", "detection", "adversary")),
    Term("timeline-building", "Timeline building",
         ("timeline", "chronology", "supertimeline", "when")),
    Term("log-analysis", "Log analysis",
         ("logs", "log", "audit", "events")),
    Term("execution-evidence", "Evidence of execution",
         ("execution", "what ran", "program execution", "launched")),
    Term("file-system-analysis", "File system analysis",
         ("filesystem", "file system", "ntfs", "metadata")),
    Term("deleted-file-recovery", "Deleted file recovery",
         ("deleted", "recovery", "carving", "carve", "unallocated")),
    Term("user-activity", "User activity",
         ("user activity", "what the user did", "behaviour", "behavior")),
    Term("persistence-analysis", "Persistence analysis",
         ("persistence", "autostart", "autoruns", "survives reboot")),
    Term("lateral-movement", "Lateral movement",
         ("lateral", "pivot", "remote logon")),
    Term("credential-access", "Credential access",
         ("credentials", "passwords", "hashes", "authentication")),
    Term("data-exfiltration", "Data exfiltration",
         ("exfiltration", "exfil", "data theft", "staging")),
    Term("cloud-activity", "Cloud activity",
         ("cloud", "sync", "file sharing")),
    Term("network-analysis", "Network analysis",
         ("network", "traffic", "connections", "dns")),
    Term("memory-analysis", "Memory analysis",
         ("memory", "ram", "volatile")),
    Term("triage-collection", "Triage and collection",
         ("triage", "collection", "acquire", "acquisition", "first response")),
    Term("reporting", "Reporting and review",
         ("reporting", "report", "review", "presentation")),
)

# What data the package reads.
ARTIFACTS = _index(
    Term("windows-event-log", "Windows event logs",
         ("evtx", "event log", "eventlog", "winevt", "security log", "sysmon")),
    Term("registry", "Windows registry",
         ("registry", "hive", "ntuser", "regf", "software hive", "system hive")),
    Term("mft", "NTFS master file table",
         ("mft", "master file table", "$mft", "ntfs")),
    Term("usn-journal", "NTFS change journal",
         ("usn", "journal", "$j", "change journal")),
    Term("prefetch", "Prefetch files",
         ("prefetch", "pf")),
    Term("amcache", "Amcache",
         ("amcache", "amcache.hve")),
    Term("shimcache", "Shimcache",
         ("shimcache", "appcompatcache", "application compatibility")),
    Term("shellbags", "Shellbags",
         ("shellbags", "shellbag", "folder access")),
    Term("jump-list", "Jump lists",
         ("jump list", "jumplist", "automaticdestinations")),
    Term("lnk", "Shortcut files",
         ("lnk", "shortcut", "link file")),
    Term("recycle-bin", "Recycle bin",
         ("recycle bin", "recyclebin", "$i30", "deleted items")),
    Term("srum", "System resource usage monitor",
         ("srum", "srudb", "resource usage")),
    Term("scheduled-task", "Scheduled tasks",
         ("scheduled task", "task scheduler", "at job")),
    Term("browser-history", "Browser history",
         ("browser", "history", "chrome", "firefox", "edge", "cookies")),
    Term("email", "Email stores",
         ("email", "mail", "pst", "ost", "mbox", "outlook")),
    Term("onedrive", "OneDrive sync logs",
         ("onedrive", "odl", "sync log", "one drive")),
    Term("sqlite", "SQLite databases",
         ("sqlite", "database", "db")),
    Term("volume-shadow-copy", "Volume shadow copies",
         ("shadow copy", "vss", "volume shadow")),
    Term("memory-image", "Memory images",
         ("memory image", "ram dump", "memory dump", "raw memory")),
    Term("disk-image", "Disk images",
         ("disk image", "e01", "raw image", "dd image", "vmdk")),
    Term("network-capture", "Network captures",
         ("pcap", "packet capture", "network capture")),
    Term("file-contents", "Arbitrary files",
         ("files", "file contents", "any file", "binaries")),
)


def _checked(values, vocabulary: dict[str, Term], field: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise ManifestError(f"{field} must be a list of strings")
    chosen = []
    for item in values:
        key = item.strip().lower()
        if key not in vocabulary:
            raise ManifestError(
                f"{field} does not recognise {item!r}. "
                f"Known values: {', '.join(sorted(vocabulary))}"
            )
        if key in chosen:
            raise ManifestError(f"{field} lists {item!r} twice")
        chosen.append(key)
    return tuple(chosen)


def checked_solves(values) -> tuple[str, ...]:
    return _checked(values, SOLVES, "solves")


def checked_artifacts(values) -> tuple[str, ...]:
    return _checked(values, ARTIFACTS, "artifacts")


def label(vocabulary: dict[str, Term], key: str) -> str:
    term = vocabulary.get(key)
    return term.label if term else key


def matching_keys(vocabulary: dict[str, Term], query: str) -> set[str]:
    """Vocabulary keys a free-text query should reach."""
    return {key for key, term in vocabulary.items() if term.matches(query)}
