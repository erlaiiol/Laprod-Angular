import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { EditTrackComponent } from './edit-track.component';

describe('EditTrackComponent', () => {
  let component: EditTrackComponent;
  let fixture: ComponentFixture<EditTrackComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [EditTrackComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(EditTrackComponent);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
