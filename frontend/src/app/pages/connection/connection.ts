import { Component, signal, OnInit } from '@angular/core';
import { OAuthService } from '../../services/oauth.service';
import { ChannelService } from '../../services/channel.service';
import { SyncService } from '../../services/sync.service';
import { SynchronizableChannel } from '../../models/channel.model';
import { ConnectionStatusResponse } from '../../models/oauth.model';
import { SyncRunResponse } from '../../models/sync.model';
import { ApiError } from '../../services/api.service';
import { LoadingSpinnerComponent } from '../../components/loading-spinner/loading-spinner';
import { EmptyStateComponent } from '../../components/empty-state/empty-state';
import { DatePipe } from '@angular/common';

@Component({
  selector: 'app-connection',
  standalone: true,
  imports: [LoadingSpinnerComponent, EmptyStateComponent, DatePipe],
  template: `
    @switch (state()) {
      @case ('loading') {
        <app-loading />
      }
      @case ('error') {
        <div class="error-banner"><p>{{ errorMessage() }}</p></div>
      }
      @case ('loaded') {
        <h2 class="page-title">Conexión de YouTube</h2>

        <section class="connect-section">
          <div class="connect-header">
            <svg class="yt-icon" viewBox="0 0 24 24" fill="currentColor">
              <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814ZM9.545 15.568V8.432L15.818 12l-6.273 3.568Z"/>
            </svg>
            <div>
              <h3>Autorización OAuth</h3>
              <p class="section-desc">
                Conecta tu canal de YouTube para que miConte pueda acceder a tus métricas privadas
                con permisos de solo lectura.
              </p>
            </div>
          </div>
          <button class="connect-btn" (click)="startAuthorization()" [disabled]="connecting()">
            {{ connecting() ? 'Generando URL...' : 'Conectar canal de YouTube' }}
          </button>
          @if (authMessage()) {
            <p class="auth-message">{{ authMessage() }}</p>
          }
        </section>

        @if (channels().length > 0) {
          <section class="channels-section">
            <h3 class="section-title">Canales conectados</h3>
            @for (ch of channels(); track ch.channel_id) {
              <div class="channel-card">
                <div class="channel-main">
                  <strong>{{ ch.title }}</strong>
                  <span class="yt-id">{{ ch.youtube_channel_id }}</span>
                  @if (ch.is_oauth_connected) {
                    <span class="status-badge connected">OAuth activo</span>
                  } @else {
                    <span class="status-badge disconnected">Sin OAuth</span>
                  }
                </div>
                <div class="channel-meta">
                  @if (ch.last_sync_at) {
                    <span>Última sync: {{ ch.last_sync_at | date:'medium' }}</span>
                    <span class="sync-status">({{ ch.last_sync_status }})</span>
                  } @else {
                    <span>Sin sincronización previa</span>
                  }
                </div>
                <div class="channel-actions">
                  <button class="action-btn" (click)="triggerSync(ch)" [disabled]="syncing()">
                    {{ syncing() ? 'Sincronizando...' : 'Sincronizar' }}
                  </button>
                  <button class="action-btn" (click)="viewStatus(ch)">
                    Ver estado
                  </button>
                  @if (ch.is_oauth_connected) {
                    <button class="action-btn danger" (click)="disconnect(ch)">
                      Desconectar
                    </button>
                  }
                </div>

                @if (connectionStatus() && statusChannelId() === ch.youtube_channel_id) {
                  <div class="status-detail">
                    <div class="status-row"><span class="status-key">Conectado</span> <span>{{ connectionStatus()!.is_connected ? 'Sí' : 'No' }}</span></div>
                    <div class="status-row"><span class="status-key">Activo</span> <span>{{ connectionStatus()!.is_active ? 'Sí' : 'No' }}</span></div>
                    <div class="status-row"><span class="status-key">Scopes</span> <span>{{ connectionStatus()!.granted_scopes }}</span></div>
                    @if (connectionStatus()!.token_expires_at) {
                      <div class="status-row"><span class="status-key">Token expira</span> <span>{{ connectionStatus()!.token_expires_at | date:'medium' }}</span></div>
                    }
                  </div>
                }

                @if (syncRuns().length > 0 && syncChannelId() === ch.channel_id) {
                  <div class="sync-history">
                    <h4>Historial de sincronización</h4>
                    @for (run of syncRuns(); track run.sync_run_id) {
                      <div class="sync-run">
                        <span class="run-status" [class]="'status-' + run.status">{{ run.status }}</span>
                        <span>{{ run.started_at | date:'short' }}</span>
                        <span>{{ run.records_processed }} registros</span>
                      </div>
                    }
                  </div>
                }
              </div>
            }
          </section>
        } @else {
          <app-empty-state
            icon="link"
            title="Sin canales"
            description="Conecta tu canal de YouTube usando el botón de autorización." />
        }
      }
    }
  `,
  styles: [`
    .page-title {
      margin: 0 0 1.5rem;
      font-size: 1.375rem;
      font-weight: 700;
      color: var(--ink);
    }
    .section-title {
      margin: 0 0 0.75rem;
      font-size: 1rem;
      font-weight: 600;
      color: var(--ink);
    }
    .section-desc {
      font-size: 0.8125rem;
      color: var(--ink-soft);
      margin: 0;
      line-height: 1.6;
    }

    .connect-section {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.5rem;
      margin-bottom: 1.5rem;
      box-shadow: var(--shadow-sm);
    }
    .connect-header {
      display: flex;
      gap: 1rem;
      align-items: flex-start;
      margin-bottom: 1rem;
    }
    .connect-header h3 {
      margin: 0 0 0.25rem;
      font-size: 1rem;
      font-weight: 600;
      color: var(--ink);
    }
    .yt-icon {
      width: 32px;
      height: 32px;
      color: #ff0000;
      flex-shrink: 0;
      margin-top: 2px;
    }
    .connect-btn {
      padding: 0.5rem 1.25rem;
      background: #dc2626;
      color: #fff;
      border: none;
      border-radius: var(--radius-sm);
      cursor: pointer;
      font-size: 0.875rem;
      font-weight: 600;
      transition: background 0.15s;
    }
    .connect-btn:hover { background: #b91c1c; }
    .connect-btn:disabled { opacity: 0.5; cursor: default; }
    .auth-message {
      margin: 0.75rem 0 0;
      font-size: 0.8125rem;
      color: var(--ink-soft);
    }

    .channels-section { margin-bottom: 1.5rem; }
    .channel-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.25rem 1.5rem;
      margin-top: 0.75rem;
      box-shadow: var(--shadow-sm);
    }
    .channel-main {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      flex-wrap: wrap;
      margin-bottom: 0.375rem;
    }
    .channel-main strong {
      color: var(--ink);
      font-weight: 600;
    }
    .yt-id {
      font-size: 0.75rem;
      color: var(--ink-faint);
      font-family: 'SF Mono', 'Cascadia Code', monospace;
    }
    .status-badge {
      font-size: 0.6875rem;
      font-weight: 600;
      padding: 0.2rem 0.5rem;
      border-radius: var(--radius-sm);
    }
    .connected { background: var(--success-bg); color: var(--success-ink); }
    .disconnected { background: var(--warn-bg); color: var(--warn-ink); }

    .channel-meta {
      font-size: 0.8125rem;
      color: var(--ink-faint);
      margin-bottom: 0.75rem;
    }
    .sync-status { font-style: italic; }

    .channel-actions {
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
    }
    .action-btn {
      padding: 0.375rem 0.875rem;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      cursor: pointer;
      font-size: 0.8125rem;
      font-weight: 500;
      color: var(--ink-soft);
      transition: background 0.15s, border-color 0.15s;
    }
    .action-btn:hover {
      background: var(--accent-subtle);
      border-color: var(--accent);
      color: var(--accent);
    }
    .action-btn:disabled { opacity: 0.5; cursor: default; }
    .action-btn.danger {
      color: var(--error-ink);
      border-color: var(--error-border);
    }
    .action-btn.danger:hover {
      background: var(--error-bg);
    }

    .status-detail {
      margin-top: 0.75rem;
      padding: 0.75rem 1rem;
      background: var(--surface);
      border-radius: var(--radius-sm);
      font-size: 0.8125rem;
      color: var(--ink-soft);
      display: grid;
      gap: 0.375rem;
    }
    .status-row {
      display: flex;
      gap: 0.75rem;
    }
    .status-key {
      font-weight: 600;
      color: var(--ink);
      min-width: 100px;
    }

    .sync-history { margin-top: 0.75rem; }
    .sync-history h4 {
      margin: 0 0 0.5rem;
      font-size: 0.875rem;
      font-weight: 600;
      color: var(--ink);
    }
    .sync-run {
      display: flex;
      gap: 0.75rem;
      font-size: 0.8125rem;
      color: var(--ink-soft);
      padding: 0.25rem 0;
    }
    .run-status { font-weight: 600; }
    .status-succeeded { color: var(--success-ink); }
    .status-failed { color: var(--error-ink); }
    .status-partially_succeeded { color: var(--warn-ink); }

    .error-banner {
      padding: 1rem 1.25rem;
      background: var(--error-bg);
      border: 1px solid var(--error-border);
      border-radius: var(--radius);
    }
    .error-banner p { margin: 0; font-size: 0.875rem; color: var(--ink); }
  `],
})
export class ConnectionComponent implements OnInit {
  state = signal<'loading' | 'loaded' | 'error'>('loading');
  channels = signal<SynchronizableChannel[]>([]);
  connectionStatus = signal<ConnectionStatusResponse | null>(null);
  statusChannelId = signal('');
  syncRuns = signal<SyncRunResponse[]>([]);
  syncChannelId = signal('');
  connecting = signal(false);
  syncing = signal(false);
  authMessage = signal('');
  errorMessage = signal('');

  constructor(
    private oauthService: OAuthService,
    private channelService: ChannelService,
    private syncService: SyncService,
  ) {}

  ngOnInit(): void {
    this.loadChannels();
  }

  startAuthorization(): void {
    this.connecting.set(true);
    this.authMessage.set('');
    this.oauthService.getAuthorizationUrl().subscribe({
      next: (res) => {
        this.connecting.set(false);
        window.location.href = res.authorization_url;
      },
      error: (err: ApiError) => {
        this.connecting.set(false);
        this.authMessage.set(`Error: ${err.message}`);
      },
    });
  }

  viewStatus(ch: SynchronizableChannel): void {
    this.connectionStatus.set(null);
    this.statusChannelId.set(ch.youtube_channel_id);
    this.oauthService.getConnectionStatus(ch.youtube_channel_id).subscribe({
      next: (status) => this.connectionStatus.set(status),
      error: (err: ApiError) => this.authMessage.set(`Error: ${err.message}`),
    });

    this.syncChannelId.set(ch.channel_id);
    this.syncService.getSyncRuns(ch.channel_id, 5).subscribe({
      next: (runs) => this.syncRuns.set(runs),
    });
  }

  triggerSync(ch: SynchronizableChannel): void {
    this.syncing.set(true);
    this.syncService.triggerSync(ch.channel_id).subscribe({
      next: () => {
        this.syncing.set(false);
        this.loadChannels();
      },
      error: (err: ApiError) => {
        this.syncing.set(false);
        this.authMessage.set(`Error de sincronización: ${err.message}`);
      },
    });
  }

  disconnect(ch: SynchronizableChannel): void {
    this.oauthService.disconnect(ch.youtube_channel_id).subscribe({
      next: (res) => {
        this.authMessage.set(res.details);
        this.loadChannels();
      },
      error: (err: ApiError) => this.authMessage.set(`Error: ${err.message}`),
    });
  }

  private loadChannels(): void {
    this.channelService.listSynchronizableChannels().subscribe({
      next: (channels) => {
        this.channels.set(channels);
        this.state.set('loaded');
      },
      error: (err: ApiError) => {
        this.errorMessage.set(err.message);
        this.state.set('error');
      },
    });
  }
}
