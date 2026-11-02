import { Component, signal, OnInit, ElementRef, ViewChild, AfterViewChecked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ChannelService } from '../../services/channel.service';
import { AnalyticsService } from '../../services/analytics.service';
import { AiService } from '../../services/ai.service';
import { ChannelSummaryResponse } from '../../models/channel.model';
import { ChannelAnalyticsResponse } from '../../models/analytics.model';
import { AIInterpretResponse, AIChatResponse, ChatMessage, MetricInput } from '../../models/ai.model';
import { ApiError } from '../../services/api.service';
import { LoadingSpinnerComponent } from '../../components/loading-spinner/loading-spinner';
import { EmptyStateComponent } from '../../components/empty-state/empty-state';
import { ComplianceNoticeComponent } from '../../components/compliance-notice/compliance-notice';
import { MetricCardComponent } from '../../components/metric-card/metric-card';
import { DecimalPipe } from '@angular/common';

type PageState = 'loading' | 'loaded' | 'no-channel' | 'compliance-blocked' | 'error';

interface AnalysisSection {
  heading: string;
  body: string;
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    FormsModule,
    LoadingSpinnerComponent,
    EmptyStateComponent,
    ComplianceNoticeComponent,
    MetricCardComponent,
    DecimalPipe,
  ],
  template: `
    @switch (state()) {
      @case ('loading') {
        <app-loading />
      }
      @case ('no-channel') {
        <app-empty-state
          icon="link"
          title="Sin canal conectado"
          description="Conecta tu canal de YouTube desde la sección de Conexión para comenzar." />
      }
      @case ('compliance-blocked') {
        <app-compliance-notice [message]="complianceMessage()" />
      }
      @case ('error') {
        <div class="error-banner">
          <p>{{ errorMessage() }}</p>
        </div>
      }
      @case ('loaded') {
        @if (summary()) {
          <section class="dashboard-header">
            <div class="channel-info">
              @if (summary()!.thumbnail_url) {
                <img
                  class="channel-thumb"
                  [src]="summary()!.thumbnail_url"
                  [alt]="summary()!.title"
                  (error)="onThumbError($event)" />
              } @else {
                <div class="channel-thumb channel-thumb-fallback" [attr.aria-label]="summary()!.title">
                  {{ summary()!.title.charAt(0).toUpperCase() }}
                </div>
              }
              <div>
                <h2>{{ summary()!.title }}</h2>
                @if (summary()!.custom_url) {
                  <span class="channel-url">{{ summary()!.custom_url }}</span>
                }
              </div>
            </div>
            @if (summary()!.snapshot) {
              <div class="snapshot-cards">
                <div class="snap-card">
                  <span class="snap-label">Visualizaciones</span>
                  <span class="snap-value">{{ summary()!.snapshot!.view_count | number }}</span>
                </div>
                <div class="snap-card">
                  <span class="snap-label">Suscriptores</span>
                  <span class="snap-value">{{ summary()!.snapshot!.subscriber_count | number }}</span>
                </div>
                <div class="snap-card">
                  <span class="snap-label">Videos</span>
                  <span class="snap-value">{{ summary()!.snapshot!.video_count | number }}</span>
                </div>
              </div>
            }
          </section>
        }

        @if (analytics()) {
          <section class="analytics-section">
            <div class="section-header">
              <h3>Analítica del canal</h3>
              <span class="period-badge">
                {{ analytics()!.period_start }} — {{ analytics()!.period_end }}
                · {{ analytics()!.n_days_with_data }} días con datos
              </span>
            </div>
            <div class="metrics-grid">
              <app-metric-card label="Visualizaciones diarias" [stats]="analytics()!.views_stats" />
              <app-metric-card label="Porcentaje medio visto (APV)" [stats]="analytics()!.apv_stats" />
              <app-metric-card label="Tasa de interacción (ER)" [stats]="analytics()!.er_stats" />
              <app-metric-card label="Conversión neta suscr. / 1k vistas" [stats]="analytics()!.nsc_1k_stats" />
            </div>
          </section>

          <!-- AI action buttons -->
          <section class="ai-actions">
            <button
              class="ai-btn ai-btn--primary"
              [disabled]="analysisLoading()"
              (click)="requestAnalysis()">
              @if (analysisLoading()) {
                <span class="btn-spinner"></span>
                Analizando...
              } @else {
                <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 0 0-2.455 2.456Z"/>
                </svg>
                Analizar mi canal
              }
            </button>
            <button
              class="ai-btn ai-btn--secondary"
              (click)="openChat()">
              <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
              </svg>
              Preguntar a miConte
            </button>
          </section>

          <!-- Structured analysis result -->
          @if (analysisError()) {
            <div class="analysis-error">
              <p>{{ analysisError() }}</p>
            </div>
          }
          @if (analysisSections().length > 0) {
            <section class="analysis-result">
              <div class="analysis-header">
                <div class="ai-badge">
                  <svg class="ai-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 0 0-2.455 2.456Z"/>
                  </svg>
                  Análisis de tu canal
                </div>
                <span class="ai-disclaimer">Basado en datos calculados por miConte · No es una medición verificada</span>
              </div>
              <div class="analysis-grid">
                @for (section of analysisSections(); track section.heading) {
                  <div class="analysis-card">
                    <h4 class="analysis-card-heading">{{ section.heading }}</h4>
                    <div class="analysis-card-body" [innerHTML]="renderBody(section.body)"></div>
                  </div>
                }
              </div>
            </section>
          }
        }
      }
    }

    <!-- Chat slide-over -->
    @if (chatOpen()) {
      <div class="chat-overlay" (click)="closeChat()"></div>
      <aside class="chat-panel">
        <div class="chat-panel-header">
          <div class="chat-panel-title">
            <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
            </svg>
            Preguntar a miConte
          </div>
          <button class="chat-close-btn" (click)="closeChat()" aria-label="Cerrar chat">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M6 18 18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <div class="chat-messages" #chatMessages>
          @if (chatHistory().length === 0) {
            <div class="chat-empty">
              <p>Hola, soy miConte AI. Puedo responder preguntas sobre los datos de tu canal en el período actual.</p>
              <p class="chat-empty-hint">¿En qué te puedo ayudar?</p>
            </div>
          }
          @for (msg of chatHistory(); track $index) {
            <div class="chat-bubble" [class.chat-bubble--user]="msg.role === 'user'" [class.chat-bubble--assistant]="msg.role === 'assistant'">
              <div class="chat-bubble-content" [innerHTML]="msg.role === 'assistant' ? renderMarkdown(msg.content) : escapeHtml(msg.content)"></div>
            </div>
          }
          @if (chatLoading()) {
            <div class="chat-bubble chat-bubble--assistant">
              <div class="chat-typing">
                <span></span><span></span><span></span>
              </div>
            </div>
          }
          @if (chatError()) {
            <div class="chat-error-msg">{{ chatError() }}</div>
          }
        </div>

        <div class="chat-input-area">
          <textarea
            class="chat-input"
            placeholder="Escribe tu pregunta..."
            rows="2"
            [disabled]="chatLoading()"
            [(ngModel)]="chatInputValue"
            (keydown.enter)="onChatEnter($event)"></textarea>
          <button
            class="chat-send-btn"
            [disabled]="chatLoading() || !chatInputValue.trim()"
            (click)="sendChatMessage()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M6 12 3.269 3.125A59.769 59.769 0 0 1 21.485 12 59.768 59.768 0 0 1 3.27 20.875L5.999 12Zm0 0h7.5"/>
            </svg>
          </button>
        </div>
        <p class="chat-footer-note">Las respuestas se basan únicamente en los datos precalculados de este período.</p>
      </aside>
    }
  `,
  styles: [`
    /* ── Page header ── */
    .dashboard-header { margin-bottom: 2rem; }
    .channel-info {
      display: flex;
      align-items: center;
      gap: 1rem;
      margin-bottom: 1.5rem;
    }
    .channel-thumb {
      width: 56px; height: 56px;
      border-radius: 50%;
      object-fit: cover;
      box-shadow: var(--shadow-sm);
      flex-shrink: 0;
    }
    .channel-thumb-fallback {
      width: 56px; height: 56px;
      border-radius: 50%;
      background: var(--accent-subtle);
      color: var(--accent);
      font-size: 1.25rem;
      font-weight: 700;
      display: none;
      align-items: center;
      justify-content: center;
      box-shadow: var(--shadow-sm);
      flex-shrink: 0;
    }
    .channel-info h2 {
      margin: 0;
      font-size: 1.375rem;
      font-weight: 700;
      color: var(--ink);
      letter-spacing: -0.01em;
    }
    .channel-url { font-size: 0.8125rem; color: var(--ink-faint); }

    /* ── Snapshot cards ── */
    .snapshot-cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 0.75rem;
    }
    .snap-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.25rem 1.5rem;
      box-shadow: var(--shadow-sm);
    }
    .snap-label {
      display: block;
      font-size: 0.8125rem;
      font-weight: 500;
      color: var(--ink-soft);
      margin-bottom: 0.375rem;
    }
    .snap-value {
      font-size: 1.5rem;
      font-weight: 700;
      color: var(--ink);
      letter-spacing: -0.02em;
    }

    /* ── Analytics section ── */
    .section-header {
      display: flex;
      align-items: baseline;
      gap: 1rem;
      flex-wrap: wrap;
      margin-bottom: 1rem;
    }
    .section-header h3 {
      margin: 0;
      font-size: 1.125rem;
      font-weight: 600;
      color: var(--ink);
    }
    .period-badge {
      font-size: 0.75rem;
      color: var(--ink-faint);
      background: var(--card);
      padding: 0.25rem 0.75rem;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
    }
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 0.75rem;
    }

    /* ── AI action buttons ── */
    .ai-actions {
      display: flex;
      gap: 0.75rem;
      margin-top: 1.75rem;
      flex-wrap: wrap;
    }
    .ai-btn {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.625rem 1.25rem;
      border-radius: var(--radius);
      font-size: 0.9375rem;
      font-weight: 600;
      cursor: pointer;
      border: none;
      transition: background 0.15s, opacity 0.15s, box-shadow 0.15s;
      line-height: 1;
    }
    .ai-btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .ai-btn--primary {
      background: var(--accent);
      color: #fff;
      box-shadow: 0 1px 4px rgba(0,0,0,0.12);
    }
    .ai-btn--primary:not(:disabled):hover { background: var(--accent-hover, var(--accent)); filter: brightness(1.08); }
    .ai-btn--secondary {
      background: var(--card);
      color: var(--accent);
      border: 1.5px solid var(--accent);
    }
    .ai-btn--secondary:hover { background: var(--accent-subtle); }
    .btn-icon { width: 18px; height: 18px; flex-shrink: 0; }
    .btn-spinner {
      width: 16px; height: 16px;
      border: 2px solid rgba(255,255,255,0.4);
      border-top-color: #fff;
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
      flex-shrink: 0;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* ── Analysis result ── */
    .analysis-error {
      margin-top: 1rem;
      padding: 0.75rem 1rem;
      background: var(--error-bg);
      border: 1px solid var(--error-border);
      border-radius: var(--radius);
      font-size: 0.875rem;
      color: var(--ink);
    }
    .analysis-result {
      margin-top: 1.5rem;
    }
    .analysis-header {
      display: flex;
      align-items: center;
      gap: 1rem;
      margin-bottom: 1rem;
      flex-wrap: wrap;
    }
    .ai-badge {
      display: flex;
      align-items: center;
      gap: 0.375rem;
      font-size: 0.875rem;
      font-weight: 600;
      color: var(--accent);
    }
    .ai-icon { width: 18px; height: 18px; }
    .ai-disclaimer {
      font-size: 0.75rem;
      color: var(--ink-faint);
      font-style: italic;
    }
    .analysis-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 0.75rem;
    }
    .analysis-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.25rem 1.5rem;
      box-shadow: var(--shadow-sm);
    }
    .analysis-card-heading {
      margin: 0 0 0.75rem;
      font-size: 0.9375rem;
      font-weight: 700;
      color: var(--accent);
    }
    .analysis-card-body {
      font-size: 0.875rem;
      line-height: 1.65;
      color: var(--ink);
    }
    .analysis-card-body ul {
      margin: 0;
      padding-left: 1.25rem;
    }
    .analysis-card-body li { margin-bottom: 0.3rem; }

    /* ── Error banner ── */
    .error-banner {
      padding: 1rem 1.25rem;
      background: var(--error-bg);
      border: 1px solid var(--error-border);
      border-radius: var(--radius);
      color: var(--ink);
    }
    .error-banner p { margin: 0; font-size: 0.875rem; }

    /* ── Chat overlay & panel ── */
    .chat-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.3);
      z-index: 200;
      animation: fadeIn 0.2s ease;
    }
    @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

    .chat-panel {
      position: fixed;
      top: 0;
      right: 0;
      bottom: 0;
      width: min(420px, 100vw);
      background: var(--surface, var(--card));
      border-left: 1px solid var(--border);
      box-shadow: -4px 0 24px rgba(0,0,0,0.12);
      z-index: 201;
      display: flex;
      flex-direction: column;
      animation: slideIn 0.22s ease;
    }
    @keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }

    .chat-panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 1rem 1.25rem;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }
    .chat-panel-title {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 1rem;
      font-weight: 700;
      color: var(--ink);
    }
    .chat-close-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 32px; height: 32px;
      border: none;
      background: transparent;
      border-radius: var(--radius-sm);
      cursor: pointer;
      color: var(--ink-soft);
      transition: background 0.15s;
    }
    .chat-close-btn:hover { background: var(--accent-subtle); }
    .chat-close-btn svg { width: 18px; height: 18px; }

    .chat-messages {
      flex: 1;
      overflow-y: auto;
      padding: 1rem 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
      scroll-behavior: smooth;
    }

    .chat-empty {
      color: var(--ink-soft);
      font-size: 0.9375rem;
      text-align: center;
      margin: auto;
      padding: 2rem 1rem;
      line-height: 1.6;
    }
    .chat-empty-hint {
      font-size: 0.875rem;
      color: var(--ink-faint);
      margin-top: 0.5rem;
    }

    .chat-bubble {
      max-width: 88%;
      border-radius: var(--radius);
      padding: 0.625rem 0.875rem;
      font-size: 0.9rem;
      line-height: 1.6;
    }
    .chat-bubble--user {
      align-self: flex-end;
      background: var(--accent);
      color: #fff;
      border-bottom-right-radius: 4px;
    }
    .chat-bubble--assistant {
      align-self: flex-start;
      background: var(--card);
      border: 1px solid var(--border);
      color: var(--ink);
      border-bottom-left-radius: 4px;
    }
    .chat-bubble-content ul { margin: 0.25rem 0; padding-left: 1.25rem; }
    .chat-bubble-content li { margin-bottom: 0.2rem; }

    .chat-typing {
      display: flex;
      gap: 5px;
      align-items: center;
      padding: 2px 4px;
    }
    .chat-typing span {
      width: 7px; height: 7px;
      border-radius: 50%;
      background: var(--ink-faint);
      animation: bounce 1.2s infinite;
    }
    .chat-typing span:nth-child(2) { animation-delay: 0.2s; }
    .chat-typing span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes bounce {
      0%, 60%, 100% { transform: translateY(0); }
      30% { transform: translateY(-6px); }
    }

    .chat-error-msg {
      font-size: 0.8125rem;
      color: var(--error-ink, #b00);
      text-align: center;
      padding: 0.25rem 0.5rem;
    }

    .chat-input-area {
      display: flex;
      gap: 0.5rem;
      align-items: flex-end;
      padding: 0.875rem 1.25rem 0.75rem;
      border-top: 1px solid var(--border);
      flex-shrink: 0;
    }
    .chat-input {
      flex: 1;
      resize: none;
      border: 1.5px solid var(--border);
      border-radius: var(--radius);
      padding: 0.5rem 0.75rem;
      font-size: 0.9375rem;
      color: var(--ink);
      background: var(--card);
      line-height: 1.5;
      font-family: inherit;
      transition: border-color 0.15s;
    }
    .chat-input:focus {
      outline: none;
      border-color: var(--accent);
    }
    .chat-input:disabled { opacity: 0.6; }
    .chat-send-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 40px; height: 40px;
      border-radius: var(--radius);
      border: none;
      background: var(--accent);
      color: #fff;
      cursor: pointer;
      flex-shrink: 0;
      transition: opacity 0.15s;
    }
    .chat-send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .chat-send-btn svg { width: 18px; height: 18px; }

    .chat-footer-note {
      font-size: 0.6875rem;
      color: var(--ink-faint);
      text-align: center;
      padding: 0 1.25rem 0.75rem;
      margin: 0;
      flex-shrink: 0;
    }
  `],
})
export class DashboardComponent implements OnInit, AfterViewChecked {
  @ViewChild('chatMessages') private chatMessagesRef?: ElementRef<HTMLDivElement>;

  state = signal<PageState>('loading');
  summary = signal<ChannelSummaryResponse | null>(null);
  analytics = signal<ChannelAnalyticsResponse | null>(null);
  errorMessage = signal('');
  complianceMessage = signal('');

  // Analysis
  analysisLoading = signal(false);
  analysisSections = signal<AnalysisSection[]>([]);
  analysisError = signal<string | null>(null);

  // Chat
  chatOpen = signal(false);
  chatHistory = signal<ChatMessage[]>([]);
  chatLoading = signal(false);
  chatError = signal<string | null>(null);
  chatInputValue = '';

  private channelId = signal<string | null>(null);
  private shouldScrollChat = false;

  constructor(
    private channelService: ChannelService,
    private analyticsService: AnalyticsService,
    private aiService: AiService,
  ) {}

  ngOnInit(): void {
    this.channelService.listSynchronizableChannels().subscribe({
      next: (channels) => {
        if (channels.length === 0) {
          this.state.set('no-channel');
          return;
        }
        this.channelId.set(channels[0].channel_id);
        this.loadSummary(channels[0].channel_id);
      },
      error: (err: ApiError) => {
        this.errorMessage.set(err.message);
        this.state.set('error');
      },
    });
  }

  ngAfterViewChecked(): void {
    if (this.shouldScrollChat) {
      this.scrollChatToBottom();
      this.shouldScrollChat = false;
    }
  }

  onThumbError(event: Event): void {
    const img = event.target as HTMLImageElement;
    img.style.display = 'none';
    const fallback = img.parentElement?.querySelector('.channel-thumb-fallback');
    if (fallback) (fallback as HTMLElement).style.display = 'flex';
  }

  requestAnalysis(): void {
    const channelId = this.channelId();
    const data = this.analytics();
    const sum = this.summary();
    if (!channelId || !data || !sum) return;

    this.analysisLoading.set(true);
    this.analysisSections.set([]);
    this.analysisError.set(null);

    this.aiService.interpretChannelAnalytics(channelId, {
      channel_title: sum.title,
      period_label: `${data.period_start} — ${data.period_end}`,
      metrics: this.buildMetrics(data),
      recommendations: [],
      mode: 'creator',
    }).subscribe({
      next: (result: AIInterpretResponse) => {
        this.analysisLoading.set(false);
        if (result.ai_summary) {
          this.analysisSections.set(this.parseAnalysisSections(result.ai_summary));
        } else {
          this.analysisError.set(result.note || 'El análisis no está disponible en este momento.');
        }
      },
      error: () => {
        this.analysisLoading.set(false);
        this.analysisError.set('No se pudo completar el análisis. Inténtalo de nuevo.');
      },
    });
  }

  openChat(): void {
    this.chatError.set(null);
    this.chatOpen.set(true);
  }

  closeChat(): void {
    this.chatOpen.set(false);
  }

  onChatEnter(event: Event): void {
    const ke = event as KeyboardEvent;
    if (!ke.shiftKey) {
      ke.preventDefault();
      this.sendChatMessage();
    }
  }

  sendChatMessage(): void {
    const text = this.chatInputValue.trim();
    if (!text || this.chatLoading()) return;

    const channelId = this.channelId();
    const data = this.analytics();
    const sum = this.summary();
    if (!channelId || !data || !sum) return;

    const userMsg: ChatMessage = { role: 'user', content: text };
    this.chatHistory.update(h => [...h, userMsg]);
    this.chatInputValue = '';
    this.chatError.set(null);
    this.chatLoading.set(true);
    this.shouldScrollChat = true;

    const history = this.chatHistory().slice(0, -1); // all before the message just added

    this.aiService.chatWithChannel(channelId, {
      message: text,
      history,
      channel_context: {
        title: sum.title,
        period_label: `${data.period_start} — ${data.period_end}`,
        metrics: this.buildMetrics(data),
        recommendations: [],
      },
    }).subscribe({
      next: (result: AIChatResponse) => {
        this.chatLoading.set(false);
        if (result.reply) {
          this.chatHistory.update(h => [...h, { role: 'assistant', content: result.reply! }]);
        } else {
          this.chatError.set(result.note || 'No se pudo obtener una respuesta.');
          this.chatHistory.update(h => h.slice(0, -1)); // remove unanswered user msg
          this.chatHistory.update(h => [...h, userMsg]); // re-add so user sees their message
        }
        this.shouldScrollChat = true;
      },
      error: () => {
        this.chatLoading.set(false);
        this.chatError.set('Error de conexión. Inténtalo de nuevo.');
        this.shouldScrollChat = true;
      },
    });
  }

  renderBody(text: string): string {
    return this.renderMarkdown(text);
  }

  renderMarkdown(text: string): string {
    let html = this.escapeHtml(text);
    // bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // bullet lines starting with "- "
    const lines = html.split('\n');
    const out: string[] = [];
    let inList = false;
    for (const line of lines) {
      const stripped = line.trim();
      if (stripped.startsWith('- ')) {
        if (!inList) { out.push('<ul>'); inList = true; }
        out.push(`<li>${stripped.slice(2)}</li>`);
      } else {
        if (inList) { out.push('</ul>'); inList = false; }
        if (stripped) out.push(`<p>${stripped}</p>`);
      }
    }
    if (inList) out.push('</ul>');
    return out.join('');
  }

  escapeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  private buildMetrics(data: ChannelAnalyticsResponse): MetricInput[] {
    return [
      { label: 'Visualizaciones diarias', value: data.views_stats.median, unit: 'views/day', n: data.views_stats.n, ci_95: data.views_stats.ci_95 as [number,number]|null, limitations: data.views_stats.limitations },
      { label: 'APV', value: data.apv_stats.median, unit: 'decimal', n: data.apv_stats.n, ci_95: data.apv_stats.ci_95 as [number,number]|null, limitations: data.apv_stats.limitations },
      { label: 'ER', value: data.er_stats.median, unit: 'decimal', n: data.er_stats.n, ci_95: data.er_stats.ci_95 as [number,number]|null, limitations: data.er_stats.limitations },
      { label: 'NSC_1k', value: data.nsc_1k_stats.median, unit: 'subs/1k', n: data.nsc_1k_stats.n, ci_95: data.nsc_1k_stats.ci_95 as [number,number]|null, limitations: data.nsc_1k_stats.limitations },
    ];
  }

  private parseAnalysisSections(text: string): AnalysisSection[] {
    const sections: AnalysisSection[] = [];
    const parts = text.split(/^## /m);
    for (const part of parts) {
      const trimmed = part.trim();
      if (!trimmed) continue;
      const newline = trimmed.indexOf('\n');
      if (newline === -1) continue;
      const heading = trimmed.slice(0, newline).trim();
      const body = trimmed.slice(newline + 1).trim();
      if (heading) sections.push({ heading, body });
    }
    return sections;
  }

  private scrollChatToBottom(): void {
    const el = this.chatMessagesRef?.nativeElement;
    if (el) el.scrollTop = el.scrollHeight;
  }

  private loadSummary(channelId: string): void {
    this.channelService.getChannelSummary(channelId).subscribe({
      next: (data) => {
        this.summary.set(data);
        this.state.set('loaded');
        this.loadAnalytics(channelId);
      },
      error: (err: ApiError) => {
        if (err.isComplianceBlock) {
          this.complianceMessage.set(err.message);
          this.state.set('compliance-blocked');
        } else {
          this.errorMessage.set(err.message);
          this.state.set('error');
        }
      },
    });
  }

  private loadAnalytics(channelId: string): void {
    this.analyticsService.getChannelAnalytics(channelId).subscribe({
      next: (data) => this.analytics.set(data),
      error: (err: ApiError) => {
        if (!err.isComplianceBlock) {
          console.warn('Error cargando analítica:', err.message);
        }
      },
    });
  }
}
