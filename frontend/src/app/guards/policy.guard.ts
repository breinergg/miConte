import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map, catchError, of, EMPTY } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { PolicyService } from '../services/policy.service';
import { AuthService } from '../services/auth.service';

export const policyGuard: CanActivateFn = () => {
  const policy = inject(PolicyService);
  const router = inject(Router);
  const auth = inject(AuthService);

  return policy.getVersions().pipe(
    map((status) => {
      if (status.all_current_accepted) {
        return true;
      }
      return router.createUrlTree(['/accept-policies']);
    }),
    catchError((err) => {
      if (err instanceof HttpErrorResponse && err.status === 401) {
        auth.initiateGoogleLogin();
        return EMPTY;
      }
      return of(router.createUrlTree(['/accept-policies']));
    }),
  );
};
