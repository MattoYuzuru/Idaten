package dev.idaten.companion.data

import android.content.Context
import android.os.Build
import java.util.UUID

class DeviceRepository(
    private val api: IdatenApi,
    private val tokenStore: TokenStore,
    private val installationId: () -> String,
    private val deviceName: () -> String = { Build.MANUFACTURER.ifBlank { "Android" } },
    private val deviceModel: () -> String = { Build.MODEL.ifBlank { "Android device" } },
    private val syncBatchStore: SyncBatchStore = InMemorySyncBatchStore(),
) {
    fun isLinked(): Boolean = tokenStore.read() != null

    suspend fun link(code: String): LinkCompleteResponse {
        val response =
            api.completeLink(
                LinkCompleteRequest(
                    code = code.trim().uppercase(),
                    installationId = installationId(),
                    deviceName = deviceName(),
                    deviceModel = deviceModel(),
                ),
            )
        tokenStore.write(response.token)
        return response
    }

    suspend fun status(): DeviceStatusResponse = api.status(requireToken())

    suspend fun sync(request: SyncRequest): SyncResponse = api.sync(requireToken(), request)

    fun beginSyncBatch(): String =
        syncBatchStore.read() ?: UUID.randomUUID().toString().also(syncBatchStore::write)

    fun completeSyncBatch() = syncBatchStore.clear()

    fun unlinkLocal() {
        tokenStore.clear()
        syncBatchStore.clear()
    }

    private fun requireToken(): String =
        tokenStore.read() ?: throw ApiException(
            "NOT_LINKED",
            "Link this device from Telegram first",
        )
}

class InstallationId(
    context: Context,
) {
    private val preferences = context.getSharedPreferences("device_identity", Context.MODE_PRIVATE)

    fun get(): String {
        preferences.getString(KEY, null)?.let { return it }
        return UUID.randomUUID().toString().also { preferences.edit().putString(KEY, it).apply() }
    }

    private companion object {
        const val KEY = "installation_id"
    }
}
