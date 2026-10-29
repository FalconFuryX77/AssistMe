package com.assistme.clicky

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse
import org.junit.Test

class ClickyTargetMatcherTest {
    private fun displays(title: String, instruction: String): List<String> =
        ClickyTargetMatcher.extractPhrases(title, instruction).map { it.display }

    private fun phrase(text: String): ClickyTargetPhrase =
        ClickyTargetPhrase(text, ClickyTargetMatcher.tokenize(text))

    @Test
    fun quotedLabelsWinOverActionWords() {
        assertEquals(listOf("Wi-Fi"), displays("Connect", "Tap the “Wi-Fi” row and wait"))
        assertEquals(listOf("Display", "Font size"), displays("", "Open 'Display' then choose \"Font size\""))
    }

    @Test
    fun apostrophesAreNotTreatedAsQuotes() {
        assertEquals(listOf("Settings"), displays("", "Don't worry, just open the Settings app"))
    }

    @Test
    fun actionPhrasesAreExtractedInOrderAndCleaned() {
        assertEquals(listOf("Settings", "Wi-Fi"), displays("", "Open Settings, then tap the Wi-Fi option."))
        assertEquals(listOf("Bluetooth"), displays("", "Turn on Bluetooth"))
        assertEquals(listOf("Save"), displays("", "Press the Save button to finish"))
        assertEquals(listOf("About phone"), displays("", "Scroll down to About phone"))
    }

    @Test
    fun menuPathsAreSplitIntoSeparateTargets() {
        assertEquals(
            listOf("Settings", "Connections", "Wi-Fi"),
            displays("", "Go to Settings > Connections → Wi-Fi"),
        )
    }

    @Test
    fun titleIsUsedOnlyAsSpecificFallback() {
        assertEquals(listOf("Battery saver"), displays("Battery saver", "Wait for the screen to change."))
        assertTrue(displays("Step 3", "Wait for the screen to change.").isEmpty())
        assertTrue(displays("", "").isEmpty())
    }

    @Test
    fun scoringHandlesPunctuationPluralsAndExtraWords() {
        assertEquals(100, ClickyTargetMatcher.score(phrase("Wi-Fi"), "Wi‑Fi"))
        assertEquals(100, ClickyTargetMatcher.score(phrase("Notification"), "Notifications"))
        assertTrue(ClickyTargetMatcher.labelMatches(phrase("Wi-Fi"), "Wi-Fi & network"))
        assertTrue(ClickyTargetMatcher.labelMatches(phrase("Sign"), "Sign in"))
        assertFalse(ClickyTargetMatcher.labelMatches(phrase("Wi-Fi"), "Mobile data"))
        assertFalse(
            ClickyTargetMatcher.labelMatches(
                phrase("Wi-Fi"),
                "Use Wi-Fi to download large updates when your phone is charging overnight",
            ),
        )
    }

    @Test
    fun tinyLabelsInsideLongerPhrasesDoNotMatch() {
        assertEquals(0, ClickyTargetMatcher.score(phrase("Turn the alarm on"), "on"))
        assertEquals(0, ClickyTargetMatcher.score(phrase("the display settings"), "the"))
    }

    @Test
    fun nonLatinScriptsKeepCombiningMarks() {
        val tokens = ClickyTargetMatcher.tokenize("सेटिंग्स")
        assertEquals(1, tokens.size)
        assertEquals(100, ClickyTargetMatcher.score(phrase("सेटिंग्स"), "सेटिंग्स"))
    }

    @Test
    fun prefersTappableElementAndSkipsRepeatedHeader() {
        val phrases = ClickyTargetMatcher.extractPhrases("", "Open Settings, then tap Wi-Fi")
        val settingsScreen = listOf(
            ClickyScreenElement("Settings", clickable = false),
            ClickyScreenElement("Network & internet", clickable = true),
            ClickyScreenElement("Wi-Fi", clickable = true),
        )
        val match = ClickyTargetMatcher.findBestMatch(phrases, 0, settingsScreen)!!
        assertEquals(1, match.phraseIndex)
        assertEquals(2, match.elementIndex)
    }

    @Test
    fun pointsAtFirstPhraseWhenItIsTappable() {
        val phrases = ClickyTargetMatcher.extractPhrases("", "Open Settings, then tap Wi-Fi")
        val homeScreen = listOf(
            ClickyScreenElement("Phone", clickable = true),
            ClickyScreenElement("Settings", clickable = true),
        )
        val match = ClickyTargetMatcher.findBestMatch(phrases, 0, homeScreen)!!
        assertEquals(0, match.phraseIndex)
        assertEquals(1, match.elementIndex)
    }

    @Test
    fun returnsNullWhenNothingMatchesOrInputsEmpty() {
        val phrases = ClickyTargetMatcher.extractPhrases("", "Tap Bluetooth")
        assertNull(ClickyTargetMatcher.findBestMatch(phrases, 0, listOf(ClickyScreenElement("Battery", true))))
        assertNull(ClickyTargetMatcher.findBestMatch(emptyList(), 0, listOf(ClickyScreenElement("Battery", true))))
        assertNull(ClickyTargetMatcher.findBestMatch(phrases, 0, emptyList()))
        // Out-of-range start index must not crash.
        assertEquals(0, ClickyTargetMatcher.findBestMatch(phrases, 99, listOf(ClickyScreenElement("Bluetooth", true)))!!.phraseIndex)
    }
}
