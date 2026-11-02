package com.assistme.clicky

/**
 * Pure-Kotlin brain of Clicky on Android: turns a saved guide step into the
 * on-screen labels it refers to, and scores visible UI elements against them.
 *
 * Deliberately free of Android imports so it can be unit tested on the JVM.
 * Everything runs on-device: no screenshot or guide text leaves the phone.
 */

/** A label Clicky should look for, in the order the step mentions it. */
data class ClickyTargetPhrase(
    /** Text shown to the user, e.g. "Wi-Fi". */
    val display: String,
    /** Normalized comparison tokens, e.g. ["wi", "fi"]. */
    val tokens: List<String>,
)

/** One visible, labelled element on the current screen. */
data class ClickyScreenElement(
    val label: String,
    val clickable: Boolean,
    /** Label guessed from a view id because the element has no text; ranked lower. */
    val weak: Boolean = false,
)

/**
 * A step done on the screen itself rather than on a labelled control, such as
 * "long-press an empty part of the home screen" or "swipe up".
 */
data class ClickyAreaHint(
    /** What Clicky asks the user to do, e.g. "Press and hold an empty part of the screen". */
    val prompt: String,
    val isSwipe: Boolean,
)

data class ClickyMatch(
    val phraseIndex: Int,
    val elementIndex: Int,
    val score: Int,
)

object ClickyTargetMatcher {
    const val MATCH_THRESHOLD = 55
    private const val CLICKABLE_BONUS = 10
    private const val WEAK_LABEL_PENALTY = 15
    private const val CONFIRM_SYNONYM_SCORE = 60
    private const val MAX_PHRASES = 8
    private const val MAX_PHRASE_WORDS = 6
    private const val MAX_LABEL_CHARACTERS = 160

    // Longest verbs first so "turn on" wins over "turn", "tap on" over "tap".
    private val actionVerbs = listOf(
        "scroll down to", "scroll up to", "navigate to", "scroll to", "look for",
        "turn on", "turn off", "switch on", "switch off", "go to", "tap on",
        "click on", "press on", "tap", "click", "press", "select", "open",
        "choose", "toggle", "enable", "disable", "find", "hit", "pick", "launch",
    )

    private val stopWords = listOf(
        "and", "then", "to", "so", "in", "on", "at", "from", "under", "which",
        "that", "until", "for", "with", "inside", "within", "next", "below",
        "above", "again", "if", "or", "button", "option", "icon", "tab",
        "toggle", "switch", "link", "when", "once", "after", "before",
    )

    private val verbPhrasePattern = Regex(
        "(?<![\\p{L}\\p{N}])(?:" +
            actionVerbs.joinToString("|") { verb ->
                verb.split(" ").joinToString("\\s+") { word -> Regex.escape(word) }
            } +
            ")\\s+(.+?)(?=$|[.,;:!?()\\n\\[\\]]|\\s+(?:" +
            stopWords.joinToString("|") +
            ")(?![\\p{L}\\p{N}]))",
        RegexOption.IGNORE_CASE,
    )

    // "double" quotes of any style, or 'single' quotes that are not apostrophes.
    private val quotePattern = Regex(
        "[\"\u201C\u201D\u201E\u00AB\u00BB]([^\"\u201C\u201D\u201E\u00AB\u00BB\\n]{1,60})[\"\u201C\u201D\u201E\u00AB\u00BB]" +
            "|(?<![\\p{L}\\p{N}])['\u2018\u2019]([^'\u2018\u2019\\n]{1,60})['\u2018\u2019](?![\\p{L}\\p{N}])",
    )

    private val pathSeparator = Regex("\\s*(?:->|=>|>|\u2192|\u203A|\u00BB)\\s*")
    private val genericStepTitle = Regex("^\\s*(?:step\\s*)?\\d+\\s*$", RegexOption.IGNORE_CASE)

    private val leadingNoise = setOf("the", "a", "an", "your", "my", "this", "that", "on", "onto", "into", "at")
    private val trailingNoise = setOf(
        "app", "application", "button", "option", "options", "icon", "tab",
        "menu", "toggle", "switch", "link", "item", "setting", "field", "box",
    )
    private val tokenStopWords = setOf(
        "the", "a", "an", "to", "of", "and", "or", "on", "in", "your", "my", "as", "for", "this", "with",
    )

    // Screens confirm with different words: a guide that says "Next" may meet
    // "Done" or "Apply" on another phone or another branch of the same flow.
    private val confirmWords = setOf(
        "next", "done", "ok", "okay", "apply", "set", "save", "confirm", "continue",
        "finish", "allow", "yes", "accept", "agree", "proceed",
    )

    private val holdPattern = Regex(
        """(?<!\p{L})(?:long[- ]?press|long[- ]?tap|press\s+and\s+hold|tap\s+and\s+hold|touch\s+and\s+hold|hold\s+down)""",
        RegexOption.IGNORE_CASE,
    )
    private val swipePattern = Regex(
        """(?<!\p{L})swipe\s+(up|down|left|right)(?!\p{L})""",
        RegexOption.IGNORE_CASE,
    )
    private val screenAreaPattern = Regex(
        """home\s*screen|empty|blank|background|anywhere|the\s+screen""",
        RegexOption.IGNORE_CASE,
    )
    // Words that describe the screen itself; they never name a control to point at.
    private val areaWords = setOf(
        "home", "screen", "homescreen", "empty", "blank", "space", "area", "background",
        "anywhere", "part", "spot", "place",
    )

    /**
     * Extracts the ordered labels a step refers to. Quoted text wins (the
     * most reliable signal); otherwise action phrases like "tap Wi-Fi" are
     * used; otherwise a short, specific step title is used as a last resort.
     */
    fun extractPhrases(title: String, instruction: String): List<ClickyTargetPhrase> {
        val phrases = extractRawPhrases(title, instruction)
        // "Long-press the home screen": the screen is the target, not a label.
        if (extractArea(title, instruction) == null) return phrases
        return phrases.filterNot { phrase -> phrase.tokens.all { it in areaWords || it in tokenStopWords } }
    }

    private fun extractRawPhrases(title: String, instruction: String): List<ClickyTargetPhrase> {
        val quoted = quotedPhrases(instruction).ifEmpty { quotedPhrases(title) }
        if (quoted.isNotEmpty()) return finalize(quoted)

        val actions = actionPhrases(instruction).ifEmpty { actionPhrases(title) }
        if (actions.isNotEmpty()) return finalize(actions)

        val cleanTitle = title.trim()
        if (cleanTitle.isNotEmpty() && !genericStepTitle.matches(cleanTitle)) {
            return finalize(pathSeparator.split(cleanTitle))
        }
        return emptyList()
    }

    /** Finds a gesture on the screen itself (press and hold, swipe), if the step asks for one. */
    fun extractArea(title: String, instruction: String): ClickyAreaHint? {
        val text = "$title. $instruction"
        swipePattern.find(text)?.let { match ->
            return ClickyAreaHint("Swipe ${match.groupValues[1].lowercase()} on the screen", isSwipe = true)
        }
        if (holdPattern.containsMatchIn(text) && screenAreaPattern.containsMatchIn(text)) {
            return ClickyAreaHint("Press and hold an empty part of the screen", isSwipe = false)
        }
        return null
    }

    private fun quotedPhrases(text: String): List<String> =
        quotePattern.findAll(text).mapNotNull { match ->
            (match.groups[1]?.value ?: match.groups[2]?.value)?.trim()?.takeIf { it.isNotEmpty() }
        }.toList()

    private fun actionPhrases(text: String): List<String> =
        verbPhrasePattern.findAll(text)
            .flatMap { match -> pathSeparator.split(match.groupValues[1]).asSequence() }
            .toList()

    private fun finalize(rawPhrases: List<String>): List<ClickyTargetPhrase> {
        val result = mutableListOf<ClickyTargetPhrase>()
        for (raw in rawPhrases) {
            val display = cleanDisplay(raw) ?: continue
            val tokens = tokenize(display)
            if (tokens.isEmpty() || tokens.size > MAX_PHRASE_WORDS) continue
            if (result.any { it.tokens == tokens }) continue
            result += ClickyTargetPhrase(display, tokens)
            if (result.size == MAX_PHRASES) break
        }
        return result
    }

    /** Strips filler like "the" or a trailing "button" while keeping the original casing. */
    private fun cleanDisplay(raw: String): String? {
        val words = raw.trim().trim('"', '\'', '\u201C', '\u201D', '\u2018', '\u2019')
            .split(Regex("\\s+")).filter { it.isNotEmpty() }.toMutableList()
        while (words.size > 1 && words.first().lowercase() in leadingNoise) words.removeAt(0)
        while (words.size > 1 && words.last().lowercase().trimEnd('.', ',') in trailingNoise) {
            words.removeAt(words.size - 1)
        }
        val display = words.joinToString(" ").trim().trimEnd('.', ',', ':', ';')
        return display.takeIf { it.isNotEmpty() }
    }

    /**
     * Lowercases, turns punctuation into spaces and lightly stems plurals.
     * Combining marks are kept so scripts such as Devanagari stay intact.
     */
    fun tokenize(text: String): List<String> {
        val builder = StringBuilder(text.length)
        for (character in text.lowercase()) {
            val type = Character.getType(character).toByte()
            val keep = Character.isLetterOrDigit(character) ||
                type == Character.NON_SPACING_MARK ||
                type == Character.COMBINING_SPACING_MARK ||
                type == Character.ENCLOSING_MARK
            builder.append(if (keep) character else ' ')
        }
        return builder.toString().split(' ').filter { it.isNotEmpty() }.map(::stem)
    }

    private fun stem(word: String): String =
        if (word.length > 3 && word.endsWith("s") && !word.endsWith("ss")) word.dropLast(1) else word

    /** Scores how well an on-screen label matches a phrase, 0..100. */
    fun score(phrase: ClickyTargetPhrase, label: String): Int {
        if (label.length > MAX_LABEL_CHARACTERS) return 0
        val labelTokens = tokenize(label)
        val phraseTokens = phrase.tokens
        if (labelTokens.isEmpty() || phraseTokens.isEmpty()) return 0
        if (labelTokens == phraseTokens) return 100
        if (phraseTokens.size == 1 && labelTokens.size == 1 &&
            phraseTokens[0] in confirmWords && labelTokens[0] in confirmWords
        ) {
            return CONFIRM_SYNONYM_SCORE
        }

        if (containsSequence(labelTokens, phraseTokens)) {
            // The label contains the whole phrase ("Wi-Fi" inside "Wi-Fi & network").
            val extraWords = labelTokens.size - phraseTokens.size
            return (90 - 8 * extraWords).coerceAtLeast(0)
        }
        if (containsSequence(phraseTokens, labelTokens)) {
            // The label is part of the phrase ("Wi-Fi" for "Wi-Fi settings").
            val meaningful = labelTokens.filter { it !in tokenStopWords }
            if (meaningful.isEmpty() || meaningful.joinToString("").length < 3) return 0
            val missingWords = phraseTokens.size - labelTokens.size
            return (85 - 12 * missingWords).coerceAtLeast(0)
        }

        val phraseSet = phraseTokens.filter { it !in tokenStopWords }.toSet()
        val labelSet = labelTokens.filter { it !in tokenStopWords }.toSet()
        val common = phraseSet intersect labelSet
        if (common.isEmpty()) return 0
        val union = phraseSet union labelSet
        return (70.0 * common.size / union.size).toInt()
    }

    fun labelMatches(phrase: ClickyTargetPhrase, label: String): Boolean =
        score(phrase, label) >= MATCH_THRESHOLD

    /**
     * Finds the element to point at. Phrases are tried in guide order starting
     * at [firstPhraseIndex]. Tappable matches are preferred, so a page header
     * that merely repeats an earlier label ("Settings") does not hide the
     * next control the user actually needs to tap.
     */
    fun findBestMatch(
        phrases: List<ClickyTargetPhrase>,
        firstPhraseIndex: Int,
        elements: List<ClickyScreenElement>,
    ): ClickyMatch? {
        if (phrases.isEmpty() || elements.isEmpty()) return null
        val start = firstPhraseIndex.coerceIn(0, phrases.size - 1)
        val bestPerPhrase = (start until phrases.size).mapNotNull { phraseIndex ->
            bestElementFor(phraseIndex, phrases[phraseIndex], elements)
        }
        return bestPerPhrase.firstOrNull { elements[it.elementIndex].clickable }
            ?: bestPerPhrase.firstOrNull()
    }

    private fun bestElementFor(
        phraseIndex: Int,
        phrase: ClickyTargetPhrase,
        elements: List<ClickyScreenElement>,
    ): ClickyMatch? {
        var best: ClickyMatch? = null
        elements.forEachIndexed { elementIndex, element ->
            val raw = score(phrase, element.label) - if (element.weak) WEAK_LABEL_PENALTY else 0
            if (raw < MATCH_THRESHOLD) return@forEachIndexed
            val ranked = raw + if (element.clickable) CLICKABLE_BONUS else 0
            if (best == null || ranked > best!!.score) {
                best = ClickyMatch(phraseIndex, elementIndex, ranked)
            }
        }
        return best
    }

    private fun containsSequence(haystack: List<String>, needle: List<String>): Boolean {
        if (needle.size > haystack.size) return false
        for (start in 0..haystack.size - needle.size) {
            if (haystack.subList(start, start + needle.size) == needle) return true
        }
        return false
    }
}
