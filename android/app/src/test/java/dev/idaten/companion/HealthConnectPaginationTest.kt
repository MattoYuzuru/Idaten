package dev.idaten.companion

import dev.idaten.companion.health.SessionPage
import dev.idaten.companion.health.collectBoundedMatches
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HealthConnectPaginationTest {
    @Test
    fun filtersAfterPagingUntilRunLimitIsReached() =
        runTest {
            val pages =
                mapOf(
                    null to SessionPage(listOf("walk-1", "bike-1"), "next"),
                    "next" to SessionPage(listOf("run-1", "walk-2", "run-2"), null),
                )
            val result =
                collectBoundedMatches(
                    limit = 2,
                    maximumPages = 4,
                    loadPage = { token -> requireNotNull(pages[token]) },
                    matches = { it.startsWith("run-") },
                )

            assertEquals(listOf("run-1", "run-2"), result.records)
            assertEquals(2, result.pagesRead)
            assertEquals(3, result.nonMatchingCount)
            assertTrue(result.exhausted)
        }

    @Test
    fun stopsAtProtectivePageLimit() =
        runTest {
            var reads = 0
            val result =
                collectBoundedMatches(
                    limit = 20,
                    maximumPages = 2,
                    loadPage = {
                        reads += 1
                        SessionPage(listOf("walk-$reads"), "page-$reads")
                    },
                    matches = { false },
                )

            assertEquals(2, reads)
            assertFalse(result.exhausted)
            assertTrue(result.records.isEmpty())
        }
}
