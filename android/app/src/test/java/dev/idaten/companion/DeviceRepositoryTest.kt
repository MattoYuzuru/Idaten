package dev.idaten.companion

import dev.idaten.companion.data.ApiException
import dev.idaten.companion.data.DeviceRepository
import dev.idaten.companion.data.DeviceStatusResponse
import dev.idaten.companion.data.IdatenApi
import dev.idaten.companion.data.InMemorySyncBatchStore
import dev.idaten.companion.data.InMemoryTokenStore
import dev.idaten.companion.data.LinkCompleteRequest
import dev.idaten.companion.data.LinkCompleteResponse
import dev.idaten.companion.data.SyncRequest
import dev.idaten.companion.data.SyncResponse
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DeviceRepositoryTest {
    @Test
    fun tokenStorageAbstractionPersistsAndClearsToken() =
        runTest {
            val store = InMemoryTokenStore()
            val api = FakeApi()
            val repository = DeviceRepository(api, store, { "installation" }, { "Pixel" }, { "9" })
            repository.link("abcd1234")
            assertTrue(repository.isLinked())
            assertEquals("issued-token", store.read())
            assertEquals("ABCD1234", api.lastLink?.code)
            repository.unlinkLocal()
            assertFalse(repository.isLinked())
        }

    @Test(expected = ApiException::class)
    fun statusRequiresStoredToken() =
        runTest {
            DeviceRepository(FakeApi(), InMemoryTokenStore(), { "installation" }).status()
        }

    @Test
    fun batchIdentitySurvivesRepositoryRestartUntilSuccess() {
        val store = InMemorySyncBatchStore()
        val first =
            DeviceRepository(
                FakeApi(),
                InMemoryTokenStore(),
                { "installation" },
                syncBatchStore = store,
            )
        val batchId = first.beginSyncBatch()
        val restarted =
            DeviceRepository(
                FakeApi(),
                InMemoryTokenStore(),
                { "installation" },
                syncBatchStore = store,
            )

        assertEquals(batchId, restarted.beginSyncBatch())
        restarted.completeSyncBatch()
        assertTrue(batchId != restarted.beginSyncBatch())
    }

    private class FakeApi : IdatenApi {
        var lastLink: LinkCompleteRequest? = null

        override suspend fun completeLink(request: LinkCompleteRequest): LinkCompleteResponse {
            lastLink = request
            return LinkCompleteResponse("device", "issued-token", "health_connect:sync")
        }

        override suspend fun status(token: String) =
            DeviceStatusResponse(
                "device",
                "Pixel",
                null,
                "health_connect:sync",
                null,
                null,
                "NEVER",
                null,
            )

        override suspend fun sync(
            token: String,
            request: SyncRequest,
        ) = SyncResponse(null, emptyList())
    }
}
