////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
//
// Module: random_access_iter.hpp
//
// Notes:
//
// Simple random access random_access_iter
//
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////

#ifndef __RANDOM_ACCESS_ITER_HPP__
#define __RANDOM_ACCESS_ITER_HPP__

////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////

template<typename __Type> class random_access_iter
{
    public: // Constructor | Destructor
        random_access_iter() { _ctor(); }
        random_access_iter(__Type* item) { _ctor(item); }
        random_access_iter(const random_access_iter& rhs) { _ctor(); _copy(rhs); }
        ~random_access_iter() { _dtor(); }

    public: // Operators
        random_access_iter& operator=(__Type* rhs) { _copy(rhs); return *this; }
        random_access_iter& operator=(const random_access_iter& rhs) { _copy(rhs); return *this; }

        random_access_iter& operator+=(const size_t rhs) { _add(rhs); return *this;}
        random_access_iter& operator-=(const size_t rhs) { _subtract(rhs); return *this;}
        
        __Type& operator*() { return *_m_ptr; }
        __Type& operator->() { return *_m_ptr; }

        __Type& operator[](const size_t index) { return _m_ptr[index]; }

        random_access_iter& operator++() { _add(1); return *this; }
        random_access_iter& operator--() { _subtract(1); return *this; }

        random_access_iter& operator++(int) { random_access_iter temp(*this); _add(1); return temp; }
        random_access_iter& operator--(int) { random_access_iter temp(*this); _subtract(1); return temp; }

        random_access_iter operator+(const random_access_iter& rhs) { return random_access_iter(_m_ptr + rhs._m_ptr); }
        random_access_iter operator-(const random_access_iter& rhs) { return random_access_iter(_m_ptr - rhs._m_ptr); }

        random_access_iter operator+(const size_t size) { return random_access_iter(_m_ptr + size); }
        random_access_iter operator-(const size_t size) { return random_access_iter(_m_ptr - size); }

        bool operator==(const random_access_iter& rhs) { return _equal(rhs); }
        bool operator!=(const random_access_iter& rhs) { return !_equal(rhs); }
        bool operator>(const random_access_iter& rhs) { return _greater_than(rhs); }
        bool operator<(const random_access_iter& rhs) { return _less_than(rhs); }
        bool operator>=(const random_access_iter& rhs) { return _greater_than(rhs) || _equal(rhs); }
        bool operator<=(const random_access_iter& rhs) { return _less_than(rhs) || _equal(rhs); }

    private: // Helpers
        void _ctor() { _m_ptr = nullptr; }
        void _ctor(__Type* item) { _m_ptr = item; }
        void _dtor() { }

        void _copy(const random_access_iter& rhs) { _m_ptr = rhs._m_ptr; }

        void _add(const size_t amount) { _m_ptr += amount; }
        void _subtract(const size_t amount) { _m_ptr -= amount; }
        
        bool _equal(const random_access_iter& rhs) { return this->_m_ptr == rhs._m_ptr; }
        bool _greater_than(const random_access_iter& rhs) { return this->_m_ptr > rhs._m_ptr; }
        bool _less_than(const random_access_iter& rhs) { return this->_m_ptr < rhs._m_ptr; }

    private: // Members
        __Type* _m_ptr;

}; // end of class(random_access_iter.hpp)

////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////

#endif // __RANDOM_ACCESS_ITER_HPP__

////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////