import { Component, signal, computed } from '@angular/core';
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
          <h1>miConte</h1>
          <span class="brand-sub">Inteligencia de contenido</span>
        </div>

        @if (activeChannel()) {
          <div class="channel-badge">
            <span class="channel-name">{{ activeChannel()!.title }}</span>
          </div>
        }

        <ul class="nav-links">
          <li>
            <a routerLink="/dashboard" routerLinkActive="active">
              <span class="nav-icon">📊</span> Panel principal
            </a>
          </li>
          <li>
            <a routerLink="/videos" routerLinkActive="active">
              <span class="nav-icon">🎬</span> Videos
            </a>
          </li>
          <li>
            <a routerLink="/recommendations" routerLinkActive="active">
              <span class="nav-icon">💡</span> Recomendaciones
            </a>
          </li>
          <li>
            <a routerLink="/connection" routerLinkActive="active">
              <span class="nav-icon">🔗</span> Conexión YouTube
            </a>
          </li>
        </ul>
      </nav>

      <div class="main-area">
        <header class="topbar">
          <button class="menu-toggle" (click)="sidebarOpen.set(!sidebarOpen())">☰</button>
          <span class="topbar-title">miConte</span>
        </header>
        <main class="content">
          <router-outlet />
        </main>
      </div>
    </div>
  `,
  styles: [`
    .shell { display: flex; min-height: 100vh; }

    .sidebar {
      width: 240px;
      background: var(--surface-sidebar);
      border-right: 1px solid var(--border-default);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
      padding: 1.5rem 0;
    }

    .brand {
      padding: 0 1.25rem 1.25rem;
      border-bottom: 1px solid var(--border-default);
    }
    .brand h1 {
      margin: 0;
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--text-primary);
    }
    .brand-sub {
      font-size: 0.6875rem;
      color: var(--text-tertiary);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    .channel-badge {
      padding: 0.75rem 1.25rem;
      border-bottom: 1px solid var(--border-default);
    }
    .channel-name {
      font-size: 0.8125rem;
      font-weight: 500;
      color: var(--text-secondary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      display: block;
    }

    .nav-links {
      list-style: none;
      padding: 0.75rem 0;
      margin: 0;
    }
    .nav-links li a {
      display: flex;
      align-items: center;
      gap: 0.625rem;
      padding: 0.625rem 1.25rem;
      color: var(--text-secondary);
      text-decoration: none;
      font-size: 0.875rem;
      transition: background 0.15s, color 0.15s;
    }
    .nav-links li a:hover { background: var(--surface-hover); }
    .nav-links li a.active {
      color: var(--color-primary);
      background: var(--surface-active);
      font-weight: 500;
    }
    .nav-icon { font-size: 1rem; width: 1.25rem; text-align: center; }

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
      border-bottom: 1px solid var(--border-default);
      background: var(--surface-card);
    }
    .menu-toggle {
      background: none;
      border: none;
      font-size: 1.25rem;
      cursor: pointer;
      color: var(--text-primary);
      padding: 0.25rem;
    }
    .topbar-title {
      font-weight: 600;
      font-size: 1rem;
      color: var(--text-primary);
    }

    .content {
      flex: 1;
      padding: 1.5rem;
      max-width: 72rem;
      width: 100%;
      margin: 0 auto;
      box-sizing: border-box;
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
      .content { padding: 1rem; }
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
