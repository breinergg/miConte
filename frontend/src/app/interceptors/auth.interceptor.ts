import { HttpInterceptorFn } from '@angular/common/http';
import { environment } from '../../environments/environment';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (environment.devUserId) {
    const cloned = req.clone({
      setHeaders: { 'X-User-Id': environment.devUserId },
    });
    return next(cloned);
  }
  return next(req);
};
