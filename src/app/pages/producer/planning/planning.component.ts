import { ChangeDetectionStrategy, Component, OnInit, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import {
  PlanningService, PlanningEventDTO, PlanningEventType,
  PLANNING_EVENT_TYPE_LABELS, PLANNING_EVENT_TYPE_ICONS,
} from '../../../services/planning.service';
import { RosterService, RosterLinkDTO } from '../../../services/roster.service';
import { AuthService } from '../../../services/auth.service';
import { ProducerTabsComponent } from '../producer-tabs/producer-tabs.component';

interface DayGroup {
  dateKey: string;
  label:   string;
  events:  PlanningEventDTO[];
}

@Component({
  selector: 'app-planning',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, ProducerTabsComponent],
  templateUrl: './planning.component.html',
  styleUrl: './planning.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PlanningComponent implements OnInit {

  readonly typeLabels = PLANNING_EVENT_TYPE_LABELS;
  readonly typeIcons  = PLANNING_EVENT_TYPE_ICONS;
  readonly typeKeys   = Object.keys(PLANNING_EVENT_TYPE_LABELS) as PlanningEventType[];

  loading     = signal(true);
  events      = signal<PlanningEventDTO[]>([]);
  activeLinks = signal<RosterLinkDTO[]>([]);

  showForm      = signal(false);
  saving        = signal(false);
  formError     = signal<string | null>(null);
  selectedLinkId = signal<number | null>(null);
  formTitle      = signal('');
  formType       = signal<PlanningEventType>('recording_session');
  formStart      = signal('');
  formEnd        = signal('');
  formLocation   = signal('');
  formDescription = signal('');

  actingOnEvent = signal<number | null>(null);

  icalFeedUrl = signal<string | null>(null);
  regenerating = signal(false);

  readonly groupedEvents = computed<DayGroup[]>(() => {
    const groups = new Map<string, DayGroup>();
    for (const e of this.events()) {
      if (e.status === 'cancelled') continue;
      const d = new Date(e.start_at);
      const dateKey = d.toISOString().slice(0, 10);
      if (!groups.has(dateKey)) {
        groups.set(dateKey, {
          dateKey,
          label: d.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' }),
          events: [],
        });
      }
      groups.get(dateKey)!.events.push(e);
    }
    return Array.from(groups.values()).sort((a, b) => a.dateKey.localeCompare(b.dateKey));
  });

  constructor(
    readonly auth: AuthService,
    private planning: PlanningService,
    private roster: RosterService,
  ) {}

  ngOnInit(): void {
    this.reload();
    this.roster.mine().subscribe({
      next: res => {
        const all = [...(res.data?.as_producer ?? []), ...(res.data?.as_artist ?? [])];
        const active = all.filter(l => l.status === 'active');
        this.activeLinks.set(active);
        if (active.length > 0) this.selectedLinkId.set(active[0].id);
      },
      error: () => {},
    });
  }

  private reload(): void {
    this.loading.set(true);
    this.planning.mine().subscribe({
      next: res => { this.events.set(res.data?.events ?? []); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  toggleForm(): void {
    this.showForm.set(!this.showForm());
    this.formError.set(null);
  }

  submitEvent(): void {
    const linkId = this.selectedLinkId();
    const title = this.formTitle().trim();
    const start = this.formStart();
    if (!linkId || !title || !start) {
      this.formError.set('Titre, roster et date de début sont obligatoires.');
      return;
    }

    this.saving.set(true);
    this.formError.set(null);
    this.planning.create(linkId, {
      title,
      event_type: this.formType(),
      start_at: start,
      end_at: this.formEnd() || undefined,
      location: this.formLocation().trim() || undefined,
      description: this.formDescription().trim() || undefined,
    }).subscribe({
      next: () => {
        this.saving.set(false);
        this.formTitle.set('');
        this.formStart.set('');
        this.formEnd.set('');
        this.formLocation.set('');
        this.formDescription.set('');
        this.showForm.set(false);
        this.reload();
      },
      error: err => {
        this.saving.set(false);
        this.formError.set(err?.error?.feedback?.message ?? "Impossible de créer l'événement.");
      },
    });
  }

  confirmEvent(e: PlanningEventDTO): void {
    this.actingOnEvent.set(e.id);
    this.planning.confirm(e.id).subscribe({
      next: () => { this.actingOnEvent.set(null); this.reload(); },
      error: () => this.actingOnEvent.set(null),
    });
  }

  cancelEvent(e: PlanningEventDTO): void {
    this.actingOnEvent.set(e.id);
    this.planning.cancel(e.id).subscribe({
      next: () => { this.actingOnEvent.set(null); this.reload(); },
      error: () => this.actingOnEvent.set(null),
    });
  }

  regenerateFeed(): void {
    this.regenerating.set(true);
    this.planning.regenerateIcalToken().subscribe({
      next: res => {
        this.regenerating.set(false);
        const path = res.data?.feed_path;
        if (path) this.icalFeedUrl.set(`${window.location.origin}${path}`);
      },
      error: () => this.regenerating.set(false),
    });
  }

  webcalUrl(url: string): string {
    return url.replace(/^https?:\/\//, 'webcal://');
  }

  copyFeedUrl(): void {
    const url = this.icalFeedUrl();
    if (url) navigator.clipboard?.writeText(url);
  }

  formatTime(iso: string): string {
    return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  }
}
