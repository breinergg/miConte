import { Routes } from '@angular/router';
import { ShellComponent } from './layout/shell';
import { policyGuard } from './guards/policy.guard';

export const routes: Routes = [
  // Policy acceptance screen — no shell, no guard
  {
    path: 'accept-policies',
    loadComponent: () =>
      import('./pages/accept-policies/accept-policies').then(
        (m) => m.AcceptPoliciesComponent,
      ),
  },
  {
    path: '',
    component: ShellComponent,
    children: [
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
      {
        path: 'dashboard',
        canActivate: [policyGuard],
        loadComponent: () =>
          import('./pages/dashboard/dashboard').then((m) => m.DashboardComponent),
      },
      {
        path: 'videos',
        canActivate: [policyGuard],
        loadComponent: () =>
          import('./pages/videos/videos').then((m) => m.VideosComponent),
      },
      {
        path: 'videos/:videoId',
        canActivate: [policyGuard],
        loadComponent: () =>
          import('./pages/video-detail/video-detail').then((m) => m.VideoDetailComponent),
      },
      {
        path: 'recommendations',
        canActivate: [policyGuard],
        loadComponent: () =>
          import('./pages/recommendations/recommendations').then(
            (m) => m.RecommendationsComponent,
          ),
      },
      {
        path: 'connection',
        canActivate: [policyGuard],
        loadComponent: () =>
          import('./pages/connection/connection').then((m) => m.ConnectionComponent),
      },
      // Exempt routes: no policy guard
      {
        path: 'privacy',
        loadComponent: () =>
          import('./pages/privacy/privacy').then((m) => m.PrivacyComponent),
      },
      {
        path: 'terms',
        loadComponent: () =>
          import('./pages/terms/terms').then((m) => m.TermsComponent),
      },
    ],
  },
  { path: '**', redirectTo: 'dashboard' },
];
