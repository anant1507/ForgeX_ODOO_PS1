document.addEventListener("DOMContentLoaded", function() {
    
    
    const menuToggle = document.getElementById("menu-toggle");
    if (menuToggle) {
        menuToggle.addEventListener("click", function(e) {
            e.preventDefault();
            document.getElementById("wrapper").classList.toggle("toggled");
        });
    }

    
    const roleSelector = document.getElementById('role');
    if (roleSelector) {
        roleSelector.addEventListener('change', function() {
            const secretCodeField = document.getElementById('secretCodeField');
            const secretCodeInput = document.getElementById('secret_code');
            if (this.value === 'manager') {
                secretCodeField.style.display = 'block';
                secretCodeInput.required = true;
            } else {
                secretCodeField.style.display = 'none';
                secretCodeInput.required = false;
            }
        });
    }

    
    const orderStatusFilter = document.getElementById('orderStatusFilter');
    if (orderStatusFilter) {
        orderStatusFilter.addEventListener('change', function() {
            const selectedStatus = this.value;
            const tableRows = document.querySelectorAll('#myOrdersTable tbody tr');
            tableRows.forEach(row => {
                const rowStatus = row.getAttribute('data-status');
                if (selectedStatus === 'all' || rowStatus === selectedStatus) {
                    row.style.display = ''; 
                } else {
                    row.style.display = 'none'; 
                }
            });
        });
    }

    
    const passwordInput = document.getElementById("password");
    const passwordValidators = {
        length: document.getElementById("length-validator"),
        uppercase: document.getElementById("uppercase-validator"),
        lowercase: document.getElementById("lowercase-validator"),
        number: document.getElementById("number-validator"),
        special: document.getElementById("special-validator")
    };
    const submitButton = document.querySelector('button[type="submit"]');

    if (passwordInput && passwordValidators.length) {
        passwordInput.addEventListener("keyup", () => {
            const password = passwordInput.value;
            let allValid = true;

            
            if (password.length >= 8) {
                passwordValidators.length.classList.add("valid");
            } else {
                passwordValidators.length.classList.remove("valid");
                allValid = false;
            }
            
            if (/[A-Z]/.test(password)) {
                passwordValidators.uppercase.classList.add("valid");
            } else {
                passwordValidators.uppercase.classList.remove("valid");
                allValid = false;
            }
            
            if (/[a-z]/.test(password)) {
                passwordValidators.lowercase.classList.add("valid");
            } else {
                passwordValidators.lowercase.classList.remove("valid");
                allValid = false;
            }
            
            if (/[0-9]/.test(password)) {
                passwordValidators.number.classList.add("valid");
            } else {
                passwordValidators.number.classList.remove("valid");
                allValid = false;
            }
            
            if (/[!@#$%^&*(),.?":{}|<>]/.test(password)) {
                passwordValidators.special.classList.add("valid");
            } else {
                passwordValidators.special.classList.remove("valid");
                allValid = false;
            }

            
            if(submitButton) {
                submitButton.disabled = !allValid;
            }
        });
    }
});