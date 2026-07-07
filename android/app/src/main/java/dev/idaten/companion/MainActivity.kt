package dev.idaten.companion

import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
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
import dev.idaten.companion.health.HealthConnectExternalActions
import dev.idaten.companion.health.HealthOnboardingState
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
    private lateinit var providerLauncher: ActivityResultLauncher<android.content.Intent>

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        permissionLauncher =
            registerForActivityResult(
                PermissionController.createRequestPermissionResultContract(),
                viewModel::onPermissionResult,
            )
        routeLauncher =
            registerForActivityResult(ExerciseRouteRequestContract()) { route: ExerciseRoute? ->
                if (::routeRecordId.isInitialized) viewModel.attachRoute(routeRecordId, route)
            }
        providerLauncher =
            registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
                viewModel.providerActionFinished()
            }
        setContent {
            MaterialTheme {
                idatenApp(
                    viewModel = viewModel,
                    requestPermissions = {
                        viewModel.requestBasePermissions()?.let(permissionLauncher::launch)
                    },
                    openProvider = ::openHealthConnect,
                    requestRoute = { recordId ->
                        routeRecordId = recordId
                        routeLauncher.launch(recordId)
                    },
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
        viewModel.onForeground()
    }

    private fun openHealthConnect() {
        if (!viewModel.startProviderAction()) return
        val action =
            HealthConnectExternalActions.firstResolvable(Build.VERSION.SDK_INT) { candidate ->
                candidate.toIntent().resolveActivity(packageManager) != null
            }
        if (action == null) {
            viewModel.providerActionFinished(started = false)
            return
        }
        providerLauncher.launch(action.toIntent())
    }
}

private enum class Screen { LINK, STATUS, RUNS }

@Composable
fun idatenApp(
    viewModel: MainViewModel,
    requestPermissions: () -> Unit,
    openProvider: () -> Unit,
    requestRoute: (String) -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var screen by remember { mutableStateOf(if (state.linked) Screen.STATUS else Screen.LINK) }
    Scaffold { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Screen.entries.forEach { item ->
                    TextButton(onClick = { screen = item }) { Text(item.title()) }
                }
            }
            state.healthMessage?.let { Text(it, color = MaterialTheme.colorScheme.tertiary) }
            state.backendMessage?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
            Spacer(Modifier.height(12.dp))
            when (screen) {
                Screen.LINK -> linkScreen(state, viewModel::updateLinkCode, viewModel::link)
                Screen.STATUS ->
                    statusScreen(
                        state,
                        requestPermissions,
                        openProvider,
                        viewModel::refreshStatus,
                    )
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

private fun Screen.title(): String =
    when (this) {
        Screen.LINK -> "Привязка"
        Screen.STATUS -> "Статус"
        Screen.RUNS -> "Пробежки"
    }

@Composable
private fun linkScreen(
    state: MainUiState,
    updateCode: (String) -> Unit,
    link: () -> Unit,
) {
    Text("Привязка устройства", style = MaterialTheme.typography.headlineSmall)
    Text("Откройте личный чат с Idaten в Telegram, выполните /link и введите одноразовый код.")
    OutlinedTextField(
        value = state.linkCode,
        onValueChange = updateCode,
        label = { Text("Код из Telegram") },
        singleLine = true,
        modifier = Modifier.fillMaxWidth().semantics { contentDescription = "Одноразовый код привязки" },
    )
    Button(
        onClick = link,
        enabled = !state.linking,
        modifier = Modifier.semantics { contentDescription = "Привязать устройство к Idaten" },
    ) {
        Text(if (state.linking) "Привязка…" else "Привязать")
    }
}

@Composable
private fun statusScreen(
    state: MainUiState,
    requestPermissions: () -> Unit,
    openProvider: () -> Unit,
    refresh: () -> Unit,
) {
    Text("Статус", style = MaterialTheme.typography.headlineSmall)
    Text(if (state.linked) "Устройство привязано" else "Устройство не привязано")
    state.status?.let {
        Text("${it.name} · ${it.scope}")
        Text("Последняя синхронизация: ${it.lastSyncStatus}${it.lastSyncAt?.let { time -> " · $time" }.orEmpty()}")
    }
    when (state.healthState) {
        HealthOnboardingState.CHECKING -> Text("Проверяем Health Connect…")
        HealthOnboardingState.PROVIDER_UPDATE_REQUIRED -> {
            Text(
                if (Build.VERSION.SDK_INT >= 34) {
                    "Требуется обновить системный модуль Health Connect в настройках устройства."
                } else {
                    "Health Connect не установлен или требует обновления."
                },
            )
            Button(
                onClick = openProvider,
                enabled = !state.providerActionInFlight,
                modifier = Modifier.semantics { contentDescription = "Установить или обновить Health Connect" },
            ) {
                Text(if (Build.VERSION.SDK_INT >= 34) "Открыть настройки Health Connect" else "Установить или обновить")
            }
        }
        HealthOnboardingState.UNSUPPORTED ->
            Text(
                "Health Connect недоступен. Нужен Android 9 или новее с Google Play Services; рабочие профили не поддерживаются.",
            )
        HealthOnboardingState.PERMISSIONS_REQUIRED -> {
            Text("Нужен доступ только на чтение: тренировки, дистанция, пульс, скорость, каденс и набор высоты.")
            Text("Маршрут не входит в этот запрос и подтверждается отдельно для каждой пробежки.")
            Button(
                onClick = requestPermissions,
                enabled = !state.permissionRequestInFlight,
                modifier = Modifier.semantics { contentDescription = "Запросить разрешения Health Connect" },
            ) {
                Text(if (state.permissionRequestInFlight) "Ожидаем ответ…" else "Предоставить доступ")
            }
        }
        HealthOnboardingState.READY -> Text("Health Connect готов к чтению пробежек")
    }
    Button(
        onClick = refresh,
        modifier = Modifier.semantics { contentDescription = "Обновить статус backend" },
    ) {
        Text("Проверить backend")
    }
}

@Composable
private fun runsScreen(
    state: MainUiState,
    load: () -> Unit,
    sync: () -> Unit,
    requestRoute: (String) -> Unit,
) {
    val healthReady = state.healthState == HealthOnboardingState.READY
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = load, enabled = healthReady && !state.loadingRuns) { Text("Последние пробежки") }
        Button(onClick = sync, enabled = healthReady && state.linked && !state.syncing) { Text("Синхронизировать") }
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
        Text(item.raw.title ?: "Пробежка", style = MaterialTheme.typography.titleMedium)
        Text("${item.raw.startedAt} · ${item.raw.distanceMeters ?: "дистанция недоступна"} м")
        when (val mapping = item.mapping) {
            is RunMappingResult.Invalid -> Text(mapping.reason, color = MaterialTheme.colorScheme.error)
            is RunMappingResult.Ready -> Text(item.syncStatus ?: "Готово к синхронизации")
        }
        item.syncMessage?.let { Text(it) }
        item.raw.routeConsentRecordId?.let { recordId ->
            TextButton(onClick = { requestRoute(recordId) }) { Text("Разрешить маршрут для этой пробежки") }
        }
    }
}
