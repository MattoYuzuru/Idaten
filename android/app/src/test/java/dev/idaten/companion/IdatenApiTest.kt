package dev.idaten.companion

import dev.idaten.companion.data.ApiException
import dev.idaten.companion.data.LinkCompleteRequest
import dev.idaten.companion.data.OkHttpIdatenApi
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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
}
