package dev.idaten.companion.data

import dev.idaten.companion.model.SyncActivityDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException

@Serializable
data class LinkCompleteRequest(
    val code: String,
    @SerialName("installation_id") val installationId: String,
    @SerialName("device_name") val deviceName: String,
    @SerialName("device_model") val deviceModel: String,
)

@Serializable
data class LinkCompleteResponse(
    @SerialName("device_id") val deviceId: String,
    val token: String,
    val scope: String,
)

@Serializable
data class SyncRequest(
    val cursor: String? = null,
    val activities: List<SyncActivityDto>,
)

@Serializable
data class SyncItemResponse(
    @SerialName("external_id") val externalId: String,
    val status: String,
    @SerialName("activity_id") val activityId: String? = null,
    @SerialName("error_code") val errorCode: String? = null,
    val message: String? = null,
)

@Serializable
data class SyncResponse(
    val cursor: String? = null,
    val items: List<SyncItemResponse>,
    val counts: SyncCounts = SyncCounts(),
)

@Serializable
data class SyncCounts(
    val saved: Int = 0,
    val duplicate: Int = 0,
    val skipped: Int = 0,
    val error: Int = 0,
)

@Serializable
data class DeviceStatusResponse(
    @SerialName("device_id") val deviceId: String,
    val name: String,
    val model: String? = null,
    val scope: String,
    @SerialName("last_sync_cursor") val lastSyncCursor: String? = null,
    @SerialName("last_sync_at") val lastSyncAt: String? = null,
    @SerialName("last_sync_status") val lastSyncStatus: String,
    @SerialName("last_sync_error") val lastSyncError: String? = null,
)

@Serializable
private data class ErrorDetail(
    val code: String? = null,
    val message: String? = null,
)

@Serializable
private data class ErrorEnvelope(
    val detail: ErrorDetail? = null,
)

class ApiException(
    val code: String,
    message: String,
) : IOException(message)

interface IdatenApi {
    suspend fun completeLink(request: LinkCompleteRequest): LinkCompleteResponse

    suspend fun status(token: String): DeviceStatusResponse

    suspend fun sync(
        token: String,
        request: SyncRequest,
    ): SyncResponse
}

class OkHttpIdatenApi(
    baseUrl: String,
    private val client: OkHttpClient = OkHttpClient(),
    private val json: Json = Json { ignoreUnknownKeys = true },
) : IdatenApi {
    private val root = baseUrl.trimEnd('/')

    override suspend fun completeLink(request: LinkCompleteRequest): LinkCompleteResponse =
        post("/health-connect/link/complete", json.encodeToString(request), null)

    override suspend fun status(token: String): DeviceStatusResponse =
        execute(
            Request
                .Builder()
                .url("$root/health-connect/sync/status")
                .header("Authorization", "Bearer $token")
                .get()
                .build(),
        )

    override suspend fun sync(
        token: String,
        request: SyncRequest,
    ): SyncResponse = post("/health-connect/sync/activities", json.encodeToString(request), token)

    private suspend inline fun <reified T> post(
        path: String,
        body: String,
        token: String?,
    ): T {
        val builder =
            Request
                .Builder()
                .url("$root$path")
                .post(body.toRequestBody(JSON_MEDIA_TYPE))
        if (token != null) builder.header("Authorization", "Bearer $token")
        return execute(builder.build())
    }

    private suspend inline fun <reified T> execute(request: Request): T =
        withContext(Dispatchers.IO) {
            client.newCall(request).execute().use { response ->
                val payload = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val error = runCatching { json.decodeFromString<ErrorEnvelope>(payload) }.getOrNull()
                    throw ApiException(
                        error?.detail?.code ?: "HTTP_${response.code}",
                        error?.detail?.message ?: "Idaten request failed (${response.code})",
                    )
                }
                runCatching { json.decodeFromString<T>(payload) }.getOrElse {
                    throw ApiException("INVALID_RESPONSE", "Idaten returned an invalid response")
                }
            }
        }

    private companion object {
        val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }
}
