import { ChangeDetectionStrategy, Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ContractBuilderService, ClauseGroupDTO, ClauseDTO, ContractType } from '../../../services/contract-builder.service';


@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-admin-contract-builder',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './admin-contract-builder.component.html',
  styleUrl: '../admin.component.scss',
})
export class AdminContractBuilderComponent implements OnInit {

  loading = signal(false);
  groups  = signal<ClauseGroupDTO[]>([]);

  // Group form
  newGroupName  = signal('');
  newGroupDesc  = signal('');
  newGroupTip   = signal('');
  newGroupType  = signal<ContractType>('exploitation');

  // Expanded group
  expandedGroupId = signal<number | null>(null);

  // Group edit modal
  editGroup    = signal<ClauseGroupDTO | null>(null);
  editGName    = signal('');
  editGDesc    = signal('');
  editGTip     = signal('');
  editGActive  = signal(true);

  // Clause create
  newClauseForms = signal<Record<number, Partial<ClauseDTO>>>({});

  // Clause edit modal
  editClause      = signal<ClauseDTO | null>(null);
  editCName       = signal('');
  editCDesc       = signal('');
  editCTipShort   = signal('');
  editCTipLong    = signal('');
  editCType       = signal('text');
  editCOptions    = signal('');
  editCRequired   = signal(false);
  editCEnabled    = signal(true);
  editCActive     = signal(true);
  editCLegalRef   = signal('');
  editCExample    = signal('');
  editCTipPlain   = signal('');

  readonly clauseTypes = [
    'text', 'textarea', 'number', 'percentage',
    'toggle', 'toggle_with_details',
    'select', 'date', 'date_range',
    'territory', 'duration', 'multi_toggle',
  ];

  constructor(private svc: ContractBuilderService) {}

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading.set(true);
    this.svc.adminGetGroups().subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) this.groups.set(res.data.groups);
      },
      error: () => this.loading.set(false),
    });
  }

  // ── Groups ────────────────────────────────────────────────────────────────

  createGroup(): void {
    const name = this.newGroupName().trim();
    if (!name) return;
    this.svc.adminCreateGroup({
      name, description: this.newGroupDesc().trim() || null,
      tooltip: this.newGroupTip().trim() || null,
      contract_type: this.newGroupType(),
    }).subscribe({
      next: res => {
        if (res.success) {
          this.newGroupName.set(''); this.newGroupDesc.set(''); this.newGroupTip.set('');
          this.load();
        }
      },
      error: () => {},
    });
  }

  openEditGroup(g: ClauseGroupDTO): void {
    this.editGroup.set(g);
    this.editGName.set(g.name);
    this.editGDesc.set(g.description ?? '');
    this.editGTip.set(g.tooltip ?? '');
    this.editGActive.set(g.is_active);
  }

  saveEditGroup(): void {
    const g = this.editGroup();
    if (!g) return;
    this.svc.adminUpdateGroup(g.id, {
      name: this.editGName().trim(),
      description: this.editGDesc().trim() || null,
      tooltip: this.editGTip().trim() || null,
      is_active: this.editGActive(),
    }).subscribe({
      next: res => {
        if (res.success) { this.editGroup.set(null); this.load(); }
      },
      error: () => {},
    });
  }

  deleteGroup(g: ClauseGroupDTO): void {
    if (!confirm(`Supprimer le groupe « ${g.name} » ?`)) return;
    this.svc.adminDeleteGroup(g.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: () => {},
    });
  }

  toggleGroup(id: number): void {
    this.expandedGroupId.update(cur => cur === id ? null : id);
  }

  // ── Clauses ───────────────────────────────────────────────────────────────

  getNewClauseForm(groupId: number): Partial<ClauseDTO> {
    return this.newClauseForms()[groupId] ?? { name: '', clause_type: 'toggle' as any };
  }

  setNewClauseField(groupId: number, field: keyof ClauseDTO, val: any): void {
    this.newClauseForms.update(m => ({
      ...m,
      [groupId]: { ...this.getNewClauseForm(groupId), [field]: val },
    }));
  }

  createClause(groupId: number): void {
    const form = this.getNewClauseForm(groupId);
    if (!form.name?.trim()) return;
    this.svc.adminCreateClause(groupId, {
      name: form.name.trim(),
      clause_type: form.clause_type,
    }).subscribe({
      next: res => {
        if (res.success) {
          this.newClauseForms.update(m => ({ ...m, [groupId]: { name: '', clause_type: 'toggle' as any } }));
          this.load();
        }
      },
      error: () => {},
    });
  }

  openEditClause(c: ClauseDTO): void {
    this.editClause.set(c);
    this.editCName.set(c.name);
    this.editCDesc.set(c.description ?? '');
    this.editCTipShort.set(c.tooltip_short ?? '');
    this.editCTipLong.set(c.tooltip_long ?? '');
    this.editCType.set(c.clause_type as string);
    this.editCOptions.set((c.options ?? []).join('\n'));
    this.editCRequired.set(c.is_required);
    this.editCEnabled.set(c.is_enabled_by_default);
    this.editCActive.set(c.is_active);
    this.editCLegalRef.set(c.legal_reference ?? '');
    this.editCExample.set(c.example_text ?? '');
    this.editCTipPlain.set(c.tooltip_plain ?? '');
  }

  saveEditClause(): void {
    const c = this.editClause();
    if (!c) return;
    const options = this.editCOptions().trim()
      ? this.editCOptions().split('\n').map(s => s.trim()).filter(Boolean)
      : null;
    this.svc.adminUpdateClause(c.id, {
      name:                  this.editCName().trim(),
      description:           this.editCDesc().trim() || null,
      tooltip_short:         this.editCTipShort().trim() || null,
      tooltip_long:          this.editCTipLong().trim() || null,
      clause_type:           this.editCType() as any,
      options,
      is_required:           this.editCRequired(),
      is_enabled_by_default: this.editCEnabled(),
      is_active:             this.editCActive(),
      legal_reference:       this.editCLegalRef().trim() || null,
      example_text:          this.editCExample().trim() || null,
      tooltip_plain:         this.editCTipPlain().trim() || null,
    } as any).subscribe({
      next: res => { if (res.success) { this.editClause.set(null); this.load(); } },
      error: () => {},
    });
  }

  deleteClause(c: ClauseDTO): void {
    if (!confirm(`Supprimer la clause « ${c.name} » ?`)) return;
    this.svc.adminDeleteClause(c.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: () => {},
    });
  }
}
