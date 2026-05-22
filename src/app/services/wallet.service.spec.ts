import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { WalletService, WalletData } from './wallet.service';
import { environment } from '../../environments/environment';

const WALLET_URL    = `${environment.apiUrl}/api/wallet`;
const CONTRACTS_URL = `${environment.apiUrl}/api/contracts`;
const STRIPE_URL    = `${environment.apiUrl}/api/stripe-connect`;

const mockWalletData: WalletData = {
  wallet: {
    balance_available: 75.5,
    balance_pending: 20.0,
    stripe_account_id: null,
    stripe_onboarding_complete: false,
    stripe_account_status: null,
  },
  transactions: [],
  show_connect_alert: true,
};

describe('WalletService', () => {
  let service: WalletService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        WalletService,
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });

    service = TestBed.inject(WalletService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  // -- getWallet() --

  it('getWallet() GETs /api/wallet', () => {
    service.getWallet().subscribe();

    const req = httpMock.expectOne(WALLET_URL);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: mockWalletData });
  });

  it('getWallet() returns wallet with correct balances', () => {
    let result: WalletData | undefined;
    service.getWallet().subscribe((res) => {
      result = res.data;
    });

    httpMock.expectOne(WALLET_URL).flush({ success: true, data: mockWalletData });

    expect(result?.wallet.balance_available).toBe(75.5);
    expect(result?.wallet.balance_pending).toBe(20.0);
  });

  // -- withdraw() --

  it('withdraw() POSTs amount to /api/wallet/withdraw', () => {
    service.withdraw(50).subscribe();

    const req = httpMock.expectOne(`${WALLET_URL}/withdraw`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ amount: 50 });
    req.flush({ success: true, data: { transfer_id: 'tr_test', amount: 50 } });
  });

  it('withdraw() sends the amount as a number (not a string)', () => {
    service.withdraw(100).subscribe();

    const req = httpMock.expectOne(`${CUD_URL}/withdraw`);
    expect(typeof req.request.body.amount).toBe('number');
    req.flush({ success: true, data: { transfer_id: 'tr_test', amount: 100 } });
  });

  // -- getMyPurchases() --

  it('getMyPurchases() GETs /api/contracts/my', () => {
    service.getMyPurchases().subscribe();

    const req = httpMock.expectOne(`${CONTRACTS_URL}/my`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { purchases: [] } });
  });

  // -- getMySales() --

  it('getMySales() GETs /api/contracts/sales', () => {
    service.getMySales().subscribe();

    const req = httpMock.expectOne(`${CONTRACTS_URL}/sales`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { sales: [], total_revenue: 0 } });
  });

  // -- getStripeStatus() --

  it('getStripeStatus() GETs /api/stripe-connect/status', () => {
    service.getStripeStatus().subscribe();

    const req = httpMock.expectOne(`${STRIPE_URL}/status`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { stripe_account_id: null, stripe_onboarding_complete: false, stripe_account_status: null } });
  });

  // -- getSetupUrl() --

  it('getSetupUrl() POSTs to /api/stripe-connect/setup-url', () => {
    service.getSetupUrl('http://localhost:4200/wallet').subscribe();

    const req = httpMock.expectOne(`${STRIPE_URL}/setup-url`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body.return_url).toBe('http://localhost:4200/wallet');
    req.flush({ success: true, data: { url: 'https://connect.stripe.com/setup' } });
  });

  // -- getDashboardUrl() --

  it('getDashboardUrl() POSTs to /api/stripe-connect/dashboard-url', () => {
    service.getDashboardUrl().subscribe();

    const req = httpMock.expectOne(`${STRIPE_URL}/dashboard-url`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, data: { url: 'https://connect.stripe.com/dashboard' } });
  });
});
