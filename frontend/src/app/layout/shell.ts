import { Component, signal } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { ChannelService } from '../services/channel.service';
import { SynchronizableChannel } from '../models/channel.model';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <div class="shell">
      <nav class="sidebar" [class.open]="sidebarOpen()">
        <div class="brand">
          <span class="brand-mark">m</span>
          <div class="brand-text">
            <span class="brand-name">miConte</span>
            <span class="brand-tag">Content Intelligence</span>
          </div>
        </div>

        @if (activeChannel()) {
          <div class="channel-badge">
            <svg class="channel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 0 1 0 1.972l-11.54 6.347a1.125 1.125 0 0 1-1.667-.986V5.653Z"/>
            </svg>
            <span class="channel-name">{{ activeChannel()!.title }}</span>
          </div>
        }

        <ul class="nav-links">
          <li>
            <a routerLink="/dashboard" routerLinkActive="active">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5M9 11.25v-5.5"/>
              </svg>
              Panel
            </a>
          </li>
          <li>
            <a routerLink="/videos" routerLinkActive="active">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9A2.25 2.25 0 0 0 13.5 5.25h-9A2.25 2.25 0 0 0 2.25 7.5v9A2.25 2.25 0 0 0 4.5 18.75Z"/>
              </svg>
              Videos
            </a>
          </li>
          <li>
            <a routerLink="/recommendations" routerLinkActive="active">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75Z"/>
              </svg>
              Recomendaciones
            </a>
          </li>
          <li>
            <a routerLink="/connection" routerLinkActive="active">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244"/>
              </svg>
              Conexión
            </a>
          </li>
        </ul>

        <div class="sidebar-footer">
          <span class="version-tag">v0.1.0</span>
        </div>
      </nav>

      <div class="main-area">
        <header class="topbar">
          <button class="menu-toggle" (click)="sidebarOpen.set(!sidebarOpen())">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5"/>
            </svg>
          </button>
          <span class="topbar-brand">miConte</span>
        </header>
        <main class="content">
          <router-outlet />
        </main>
      </div>

      @if (sidebarOpen()) {
        <div class="backdrop" (click)="sidebarOpen.set(false)"></div>
      }
    </div>
  `,
  styles: [`
    .shell { display: flex; min-height: 100vh; }

    .sidebar {
      width: 248px;
      background: var(--sidebar-bg);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
      padding: 1.5rem 0 1rem;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      padding: 0 1.25rem 1.5rem;
    }
    .brand-mark {
      width: 36px;
      height: 36px;
      background: var(--accent);
      color: #fff;
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 1.125rem;
      flex-shrink: 0;
    }
    .brand-name {
      font-size: 1.125rem;
      font-weight: 700;
      color: #fff;
      display: block;
      line-height: 1.2;
    }
    .brand-tag {
      font-size: 0.6875rem;
      color: var(--sidebar-ink-faint);
      letter-spacing: 0.02em;
    }

    .channel-badge {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin: 0 0.75rem 1rem;
      padding: 0.5rem 0.75rem;
      background: var(--sidebar-hover);
      border-radius: var(--radius-sm);
    }
    .channel-icon {
      width: 16px;
      height: 16px;
      color: var(--sidebar-ink-faint);
      flex-shrink: 0;
    }
    .channel-name {
      font-size: 0.8125rem;
      font-weight: 500;
      color: var(--sidebar-ink);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .nav-links {
      list-style: none;
      padding: 0;
      margin: 0;
      flex: 1;
    }
    .nav-links li a {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      padding: 0.625rem 1.25rem;
      color: var(--sidebar-ink-faint);
      text-decoration: none;
      font-size: 0.875rem;
      font-weight: 500;
      transition: background 0.15s, color 0.15s;
      border-left: 3px solid transparent;
    }
    .nav-links li a:hover {
      background: var(--sidebar-hover);
      color: var(--sidebar-ink);
    }
    .nav-links li a.active {
      color: #fff;
      background: var(--sidebar-active);
      border-left-color: var(--accent);
    }
    .nav-icon {
      width: 20px;
      height: 20px;
      flex-shrink: 0;
    }

    .sidebar-footer {
      padding: 0.75rem 1.25rem 0;
      border-top: 1px solid var(--sidebar-hover);
    }
    .version-tag {
      font-size: 0.6875rem;
      color: var(--sidebar-ink-faint);
    }

    .main-area {
      flex: 1;
      display: flex;
      flex-direction: column;
      min-width: 0;
    }

    .topbar {
      display: none;
      align-items: center;
      gap: 0.75rem;
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--border);
      background: var(--card);
    }
    .menu-toggle {
      background: none;
      border: none;
      cursor: pointer;
      color: var(--ink);
      padding: 0.25rem;
      width: 32px;
      height: 32px;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .menu-toggle svg { width: 22px; height: 22px; }
    .topbar-brand {
      font-weight: 700;
      font-size: 1rem;
      color: var(--ink);
    }

    .content {
      flex: 1;
      padding: 2rem;
      max-width: 72rem;
      width: 100%;
      margin: 0 auto;
      box-sizing: border-box;
    }

    .backdrop {
      display: none;
    }

    @media (max-width: 768px) {
      .sidebar {
        position: fixed;
        left: 0; top: 0; bottom: 0;
        z-index: 100;
        transform: translateX(-100%);
        transition: transform 0.2s ease;
      }
      .sidebar.open { transform: translateX(0); }
      .topbar { display: flex; }
      .content { padding: 1.25rem 1rem; }
      .backdrop {
        display: block;
        position: fixed;
        inset: 0;
        z-index: 99;
        background: rgba(0, 0, 0, 0.4);
      }
    }
  `],
})
export class ShellComponent {
  sidebarOpen = signal(false);
  activeChannel = signal<SynchronizableChannel | null>(null);

  constructor(private channelService: ChannelService) {
    this.loadChannel();
  }

  private loadChannel(): void {
    this.channelService.listSynchronizableChannels().subscribe({
      next: (channels) => {
        if (channels.length > 0) {
          this.activeChannel.set(channels[0]);
        }
      },
    });
  }
}
