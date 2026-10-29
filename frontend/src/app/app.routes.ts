import { Routes } from '@angular/router';
import { ShellComponent } from './layout/shell';

export const routes: Routes = [
  {
    path: '',
    component: ShellComponent,
    children: [
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
      {
        path: 'dashboard',
        loadComponent: () =>
          import('./pages/dashboard/dashboard').then((m) => m.DashboardComponent),
      },
      {
        path: 'videos',
        loadComponent: () =>
          import('./pages/videos/videos').then((m) => m.VideosComponent),
      },
      {
        path: 'videos/:videoId',
        loadComponent: () =>
          import('./pages/video-detail/video-detail').then((m) => m.VideoDetailComponent),
      },
      {
        path: 'recommendations',
        loadComponent: () =>
          import('./pages/recommendations/recommendations').then(
            (m) => m.RecommendationsComponent,
          ),
      },
      {
        path: 'connection',
        loadComponent: () =>
          import('./pages/connection/connection').then((m) => m.ConnectionComponent),
      },
    ],
  },
  { path: '**', redirectTo: 'dashboard' },
];
