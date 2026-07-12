package dev.idaten.companion

import dev.idaten.companion.data.ApiException
import dev.idaten.companion.data.LinkCompleteRequest
import dev.idaten.companion.data.OkHttpIdatenApi
import dev.idaten.companion.model.SyncSleepDto
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class IdatenApiTest {
    @Test
    fun linkErrorIsMappedWithoutLeakingPayload() =
        runTest {
            val server = MockWebServer()
            server.enqueue(
                MockResponse().setResponseCode(400).setBody(
                    """{"detail":{"code":"INVALID_LINK_CODE","message":"Invalid code"}}""",
                ),
            )
            server.start()
            try {
                val api = OkHttpIdatenApi(server.url("/").toString())
                val error =
                    runCatching {
                        api.completeLink(LinkCompleteRequest("AAAAAAAA", "install", "Pixel", "9"))
                    }.exceptionOrNull() as ApiException
                assertEquals("INVALID_LINK_CODE", error.code)
                assertEquals("Invalid code", error.message)
                assertFalse(error.message.orEmpty().contains("detail"))
            } finally {
                server.shutdown()
            }
        }

    @Test
    fun statusAuthFailureIsMapped() =
        runTest {
            val server = MockWebServer()
            server.enqueue(MockResponse().setResponseCode(403).setBody("{}"))
            server.start()
            try {
                val error =
                    runCatching {
                        OkHttpIdatenApi(server.url("/").toString()).status("revoked")
                    }.exceptionOrNull() as ApiException
                assertEquals("HTTP_403", error.code)
            } finally {
                server.shutdown()
            }
        }

    @Test
    fun sleepSyncUsesDeviceAuthAndContainsNoRawStages() =
        runTest {
            val server = MockWebServer()
            server.enqueue(
                MockResponse().setBody(
                    """{"summary_id":"summary-1","created":true}""",
                ),
            )
            server.start()
            try {
                val response =
                    OkHttpIdatenApi(server.url("/").toString()).syncSleep(
                        "device-token",
                        SyncSleepDto(
                            externalId = "sleep-1",
                            startedAt = "2026-07-11T22:00:00Z",
                            endedAt = "2026-07-12T06:00:00Z",
                            durationSeconds = 28_800,
                            dataOrigin = "com.samsung.health",
                        ),
                    )
                val request = server.takeRequest()
                val body = request.body.readUtf8()

                assertTrue(response.created)
                assertEquals("/health-connect/sync/sleep", request.path)
                assertEquals("Bearer device-token", request.getHeader("Authorization"))
                assertFalse(body.contains("stages"))
                assertFalse(body.contains("raw"))
            } finally {
                server.shutdown()
            }
        }
}
