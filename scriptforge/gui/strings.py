"""UI strings and the colour system.

Both live in one module because both are repainted wholesale when the user hits
the AR/EN toggle: a partial retranslate leaves stale labels behind, which is
worse than a full one. Rebuilt_at() is the single choke point.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- palette ---------------------------------------------------------------
# Chosen for a dark tool surface: chrome recedes, content and prompt markers
# carry the contrast. Values are not themeable at runtime yet on purpose.
BG = "#12141a"
BG_PANEL = "#191c24"
BG_RAISED = "#21252f"
BORDER = "#2c313d"
FG = "#e6e9ef"
FG_DIM = "#8b93a5"
FG_FAINT = "#5d6577"
ACCENT = "#f0a028"
ACCENT_DEEP = "#c97a12"
OK = "#3fb950"
WARN = "#d29922"
ERR = "#f85149"
INFO = "#58a6ff"

# Script kinds get distinct hues so a list of 40 entries stays scannable.
KIND_COLOURS = {
    "interactive": INFO,
    "parametric": ACCENT,
    "skeletal": WARN,
    "fullscreen": "#a371f7",
    "opaque": FG_FAINT,
}


@dataclass(frozen=True)
class Strings:
    """One complete UI vocabulary. Every visible literal is a field here."""

    lang: str
    # window / toolbar
    app_title: str
    search: str
    search_hint: str
    rescan: str
    forge: str
    run: str
    stop: str
    clear: str
    language: str
    tabs_overview: str
    tabs_interface: str
    tabs_run: str
    tabs_history: str
    # overview
    no_selection: str
    no_selection_hint: str
    field_path: str
    field_lang: str
    field_kind: str
    field_size: str
    field_modified: str
    section_questions: str
    section_args: str
    section_flags: str
    section_commands: str
    none: str
    # interface
    no_fields: str
    no_fields_hint: str
    field_checkbox: str
    yes_short: str
    no_short: str
    answers_ready: str
    fill_optional_hint: str
    more_optional: str
    regenerating: str
    forged: str
    forge_failed: str
    not_buildable: str
    reused: str
    # run
    console_empty: str
    running: str
    finished: str
    timed_out: str
    exit_code: str
    answers_label: str
    # history
    history_empty: str
    col_script: str
    col_exit: str
    col_when: str
    col_seconds: str
    # status
    ready: str
    scripts_found: str
    parse_failed: str

    @property
    def rtl(self) -> bool:
        return self.lang == "ar"


EN = Strings(
    lang="en",
    app_title="ScriptForge",
    search="Search",
    search_hint="filter by name or path…",
    rescan="Rescan",
    forge="Build interface",
    run="Run",
    stop="Stop",
    clear="Clear",
    language="عربي",
    tabs_overview="Overview",
    tabs_interface="Interface",
    tabs_run="Run",
    tabs_history="History",
    no_selection="No script selected",
    no_selection_hint="Pick a script on the left to inspect it.",
    field_path="Path",
    field_lang="Language",
    field_kind="Kind",
    field_size="Size",
    field_modified="Modified",
    section_questions="Questions",
    section_args="Arguments",
    section_flags="Flags",
    section_commands="Sub-commands",
    none="none",
    no_fields="This script has no built-in interface",
    no_fields_hint=(
        "A script with no prompts and no arguments is driven entirely by files "
        "and flags. Build an interface to wrap it in a menu."
    ),
    field_checkbox="use this script",
    yes_short="y",
    no_short="n",
    answers_ready="answers ready",
    fill_optional_hint="Only the fields without a default are required. Press Run to accept the rest.",
    more_optional="optional fields",
    regenerating="Building interface…",
    forged="Interface written",
    forge_failed="Build failed",
    reused="Up to date",
    not_buildable="This script delegates elsewhere — there is no interface to build.",
    console_empty="Output appears here.",
    running="running…",
    finished="finished",
    timed_out="timed out",
    exit_code="exit",
    answers_label="Answers",
    history_empty="No runs recorded yet.",
    col_script="Script",
    col_exit="Exit",
    col_when="When",
    col_seconds="Time",
    ready="ready",
    scripts_found="scripts",
    parse_failed="could not parse",
)

AR = Strings(
    lang="ar",
    app_title="سكربت فورج",
    search="بحث",
    search_hint="ابحث بالاسم أو المسار…",
    rescan="تحديث",
    forge="بناء الواجهة",
    run="تشغيل",
    stop="إيقاف",
    clear="مسح",
    language="English",
    tabs_overview="نظرة عامة",
    tabs_interface="الواجهة",
    tabs_run="التشغيل",
    tabs_history="السجل",
    no_selection="ما في سكربت محدد",
    no_selection_hint="اختر سكربت من اليمين لتفحصه.",
    field_path="المسار",
    field_lang="اللغة",
    field_kind="النوع",
    field_size="الحجم",
    field_modified="آخر تعديل",
    section_questions="الأسئلة",
    section_args="المعاملات",
    section_flags="المفاتيح",
    section_commands="الأوامر",
    none="لا يوجد",
    no_fields="هذا السكربت ما فيه واجهة جاهزة",
    no_fields_hint=(
        "سكربت بدون أسئلة أو معاملات بينتحكم فيه ملفات ومفاتيح. "
        "ابنِ واجهة لتحوّله إلى قائمة."
    ),
    field_checkbox="استخدم هذا السكربت",
    yes_short="نعم",
    no_short="لا",
    answers_ready="الجاهز للإجابة",
    fill_optional_hint="الحقول اللي إلها قيمة افتراضية مش مطلوبة. اضغط «تشغيل» لباقيهم.",
    more_optional="حقول اختيارية",
    regenerating="جارٍ بناء الواجهة…",
    forged="تم كتابة الواجهة",
    forge_failed="فشل البناء",
    reused="محدّث",
    not_buildable="هذا السكربت بيفوّض شغله لبرنامج تاني — ما فيه واجهة نبنيها.",
    console_empty="المخرجات بتظهر هون.",
    running="شغّال…",
    finished="خلص",
    timed_out="انتهى الوقت",
    exit_code="الخروج",
    answers_label="الإجابات",
    history_empty="ما في تشغيلات مسجّلة.",
    col_script="السكربت",
    col_exit="الخروج",
    col_when="الوقت",
    col_seconds="المدة",
    ready="جاهز",
    scripts_found="سكربت",
    parse_failed="ما انقرأ",
)


CATALOG = {"en": EN, "ar": AR}