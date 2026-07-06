package dev.idaten.companion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.contracts.ExerciseRouteRequestContract
import androidx.health.connect.client.records.ExerciseRoute
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.idaten.companion.data.AndroidKeystoreTokenStore
import dev.idaten.companion.data.DeviceRepository
import dev.idaten.companion.data.InstallationId
import dev.idaten.companion.data.OkHttpIdatenApi
import dev.idaten.companion.health.AndroidHealthConnectSource
import dev.idaten.companion.model.HealthAvailability
import dev.idaten.companion.model.RunItem
import dev.idaten.companion.model.RunMappingResult

class MainActivity : ComponentActivity() {
    private val health by lazy { AndroidHealthConnectSource(this) }
    private val installationId by lazy { InstallationId(this) }
    private val devices by lazy {
        DeviceRepository(
            api = OkHttpIdatenApi(BuildConfig.IDATEN_BASE_URL),
            tokenStore = AndroidKeystoreTokenStore(this),
            installationId = installationId::get,
        )
    }
    private val viewModel by viewModels<MainViewModel> { MainViewModel.Factory(devices, health) }
    private lateinit var routeRecordId: String
    private lateinit var permissionLauncher: ActivityResultLauncher<Set<String>>
    private lateinit var routeLauncher: ActivityResultLauncher<String>

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        permissionLauncher =
            registerForActivityResult(
                PermissionController.createRequestPermissionResultContract(),
            ) { viewModel.refreshPermissions() }
        routeLauncher =
            registerForActivityResult(ExerciseRouteRequestContract()) { route: ExerciseRoute? ->
                if (::routeRecordId.isInitialized) viewModel.attachRoute(routeRecordId, route)
            }
        setContent {
            MaterialTheme {
                idatenApp(
                    viewModel = viewModel,
                    requestPermissions = { permissionLauncher.launch(health.basePermissions) },
                    requestRoute = { recordId ->
                        routeRecordId = recordId
                        routeLauncher.launch(recordId)
                    },
                )
            }
        }
    }
}

private enum class Screen { LINK, STATUS, RUNS }

@Composable
fun idatenApp(
    viewModel: MainViewModel,
    requestPermissions: () -> Unit,
    requestRoute: (String) -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var screen by remember { mutableStateOf(if (state.linked) Screen.STATUS else Screen.LINK) }
    Scaffold { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Screen.entries.forEach { item ->
                    TextButton(onClick = { screen = item }) { Text(item.name.lowercase()) }
                }
            }
            state.message?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
            Spacer(Modifier.height(12.dp))
            when (screen) {
                Screen.LINK -> linkScreen(state, viewModel::updateLinkCode, viewModel::link)
                Screen.STATUS -> statusScreen(state, requestPermissions, viewModel::refreshStatus)
                Screen.RUNS ->
                    runsScreen(
                        state,
                        viewModel::loadLatestRuns,
                        viewModel::sync,
                        requestRoute,
                    )
            }
        }
    }
}

@Composable
private fun linkScreen(
    state: MainUiState,
    updateCode: (String) -> Unit,
    link: () -> Unit,
) {
    Text("Link device", style = MaterialTheme.typography.headlineSmall)
    Text("Open Idaten in Telegram, run /link, then enter the one-time code.")
    OutlinedTextField(
        value = state.linkCode,
        onValueChange = updateCode,
        label = { Text("Telegram link code") },
        singleLine = true,
        modifier = Modifier.fillMaxWidth(),
    )
    Button(onClick = link, enabled = !state.linking) { Text("Link") }
}

@Composable
private fun statusScreen(
    state: MainUiState,
    requestPermissions: () -> Unit,
    refresh: () -> Unit,
) {
    Text("Status", style = MaterialTheme.typography.headlineSmall)
    Text(if (state.linked) "Device linked" else "Device not linked")
    state.status?.let {
        Text("${it.name} · ${it.scope}")
        Text("Last sync: ${it.lastSyncStatus}${it.lastSyncAt?.let { time -> " · $time" }.orEmpty()}")
    }
    when (state.permissionState?.healthConnect) {
        HealthAvailability.AVAILABLE ->
            Text(
                if (state.permissionState.baseGranted) {
                    "Health Connect permissions granted"
                } else {
                    "Health Connect permissions required"
                },
            )
        HealthAvailability.UPDATE_REQUIRED -> Text("Health Connect provider update required")
        HealthAvailability.UNAVAILABLE -> Text("Health Connect unavailable")
        null -> Text("Checking Health Connect")
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = requestPermissions) { Text("Permissions") }
        Button(onClick = refresh) { Text("Refresh") }
    }
}

@Composable
private fun runsScreen(
    state: MainUiState,
    load: () -> Unit,
    sync: () -> Unit,
    requestRoute: (String) -> Unit,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = load, enabled = !state.loadingRuns) { Text("Latest runs") }
        Button(onClick = sync, enabled = state.linked && !state.syncing) { Text("Manual Sync") }
    }
    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(state.runs, key = { it.raw.externalId }) { item -> runRow(item, requestRoute) }
    }
}

@Composable
private fun runRow(
    item: RunItem,
    requestRoute: (String) -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        Text(item.raw.title ?: "Run", style = MaterialTheme.typography.titleMedium)
        Text("${item.raw.startedAt} · ${item.raw.distanceMeters ?: "distance unavailable"} m")
        when (val mapping = item.mapping) {
            is RunMappingResult.Invalid -> Text(mapping.reason, color = MaterialTheme.colorScheme.error)
            is RunMappingResult.Ready -> Text(item.syncStatus ?: "Ready")
        }
        item.syncMessage?.let { Text(it) }
        item.raw.routeConsentRecordId?.let { recordId ->
            TextButton(onClick = { requestRoute(recordId) }) { Text("Allow route for this run") }
        }
    }
}
