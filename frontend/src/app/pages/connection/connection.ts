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
        <h2>Conexión de YouTube</h2>

        <section class="connect-section">
          <h3>Autorización OAuth</h3>
          <p class="section-desc">
            Conecta tu canal de YouTube para que miConte pueda acceder a tus métricas privadas
            con permisos de solo lectura.
          </p>
          <button class="connect-btn" (click)="startAuthorization()" [disabled]="connecting()">
            {{ connecting() ? 'Generando URL...' : 'Conectar canal de YouTube' }}
          </button>
          @if (authMessage()) {
            <p class="auth-message">{{ authMessage() }}</p>
          }
        </section>

        @if (channels().length > 0) {
          <section class="channels-section">
            <h3>Canales conectados</h3>
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
                    <div><strong>Conectado:</strong> {{ connectionStatus()!.is_connected ? 'Sí' : 'No' }}</div>
                    <div><strong>Activo:</strong> {{ connectionStatus()!.is_active ? 'Sí' : 'No' }}</div>
                    <div><strong>Scopes:</strong> {{ connectionStatus()!.granted_scopes }}</div>
                    @if (connectionStatus()!.token_expires_at) {
                      <div><strong>Token expira:</strong> {{ connectionStatus()!.token_expires_at | date:'medium' }}</div>
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
            icon="🔗"
            title="Sin canales"
            description="Conecta tu canal de YouTube usando el botón de autorización." />
        }
      }
    }
  `,
  styles: [`
    h2 { margin: 0 0 1.5rem; font-size: 1.25rem; color: var(--text-primary); }
    h3 { margin: 0 0 0.5rem; font-size: 1rem; color: var(--text-primary); }
    .section-desc {
      font-size: 0.8125rem;
      color: var(--text-secondary);
      margin: 0 0 0.75rem;
      line-height: 1.5;
    }

    .connect-section {
      background: var(--surface-card);
      border: 1px solid var(--border-default);
      border-radius: 8px;
      padding: 1.25rem;
      margin-bottom: 1.5rem;
    }
    .connect-btn {
      padding: 0.5rem 1.25rem;
      background: #dc2626;
      color: #fff;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.875rem;
      font-weight: 500;
    }
    .connect-btn:hover { opacity: 0.9; }
    .connect-btn:disabled { opacity: 0.5; cursor: default; }
    .auth-message {
      margin: 0.75rem 0 0;
      font-size: 0.8125rem;
      color: var(--text-secondary);
    }

    .channels-section { margin-bottom: 1.5rem; }
    .channel-card {
      background: var(--surface-card);
      border: 1px solid var(--border-default);
      border-radius: 8px;
      padding: 1.25rem;
      margin-top: 0.75rem;
    }
    .channel-main {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      flex-wrap: wrap;
      margin-bottom: 0.375rem;
    }
    .channel-main strong { color: var(--text-primary); }
    .yt-id { font-size: 0.75rem; color: var(--text-tertiary); font-family: monospace; }
    .status-badge {
      font-size: 0.6875rem;
      font-weight: 600;
      padding: 0.15rem 0.5rem;
      border-radius: 4px;
    }
    .connected { background: #dcfce7; color: #166534; }
    .disconnected { background: #fef3c7; color: #92400e; }

    .channel-meta {
      font-size: 0.8125rem;
      color: var(--text-tertiary);
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
      background: var(--surface-card);
      border: 1px solid var(--border-default);
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.8125rem;
      color: var(--text-secondary);
    }
    .action-btn:hover { background: var(--surface-hover); }
    .action-btn:disabled { opacity: 0.5; cursor: default; }
    .action-btn.danger { color: #dc2626; border-color: #fca5a5; }
    .action-btn.danger:hover { background: #fef2f2; }

    .status-detail {
      margin-top: 0.75rem;
      padding: 0.75rem;
      background: var(--surface-hover);
      border-radius: 6px;
      font-size: 0.8125rem;
      color: var(--text-secondary);
      display: grid;
      gap: 0.25rem;
    }

    .sync-history { margin-top: 0.75rem; }
    .sync-history h4 { margin: 0 0 0.5rem; font-size: 0.875rem; color: var(--text-primary); }
    .sync-run {
      display: flex;
      gap: 0.75rem;
      font-size: 0.8125rem;
      color: var(--text-secondary);
      padding: 0.25rem 0;
    }
    .run-status { font-weight: 500; }
    .status-succeeded { color: #166534; }
    .status-failed { color: #b91c1c; }
    .status-partially_succeeded { color: #92400e; }

    .error-banner {
      padding: 1rem 1.25rem;
      background: var(--surface-error);
      border: 1px solid var(--border-error);
      border-radius: 8px;
    }
    .error-banner p { margin: 0; font-size: 0.875rem; color: var(--text-primary); }
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
